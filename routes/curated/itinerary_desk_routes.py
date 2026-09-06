"""routes/curated/itinerary_desk_routes.py

The itinerary desk: a request on the left, two proposed day-code sequences on
the right, and a comment that asks the model to answer again.

The model proposes and the vendored rules propose, on every request. Neither is
authoritative, so a disagreement is shown rather than resolved here.

Nothing on this surface writes to the operations sheet. A document is generated
only when it is asked for, because generation renders a Google Doc.
"""

import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.middleware import require_admin

from services.itinerary.drafts import (
    ORIGIN_SHEET,
    RULE_STATE_DRAFTED,
    RULE_STATES,
    draft_id_for,
    ORIGIN_TYPED,
    SOURCE_MODEL,
    SOURCE_RULES,
    DraftError,
    add_comment,
    add_sequence,
    iter_comments,
    iter_drafts,
    load,
    open_draft,
    save,
    sequences_agree,
    set_comment_rule_state,
)
from services.itinerary.normalizer import normalize_from_dict
from services.itinerary.propose_sequence import (
    ModelProposalsDisabled,
    ProposalError,
    active_day_templates,
    field_of,
    model_proposals_enabled,
    propose_by_model,
    propose_by_rules,
)

logger = logging.getLogger(__name__)


# The worklist sources that carry a tour request. Bookings and contacts are the
# other two, and neither describes a trip to build (ws-03 D14).
REQUEST_SOURCES = ("curated", "queue")


class RequestRow(BaseModel):
    # The column dict normalize_row already reads. One shape serves a pasted
    # request and a fetched sheet row alike.
    row: dict
    origin: str = ORIGIN_TYPED


class WorklistRequest(BaseModel):
    # "curated:<id>" or "queue:<row_id>", as the worklist writes it.
    key: str


class CommentVerdict(BaseModel):
    # What became of one comment once it was read for a rule.
    rule_state: str


class JudgedRuleDraft(BaseModel):
    """
    A rule drafted from one comment, waiting for the owner's accept.

    `family` and `subject` are filled only where the rule speaks about something
    the counter also measures, so the corpus can be asked about it. Left empty,
    the rule is stored with a `silent` verdict, which is the truthful answer.
    """
    draft_id: str
    comment_id: str
    statement: str
    family: str = ""
    subject: str = ""
    corrected_sequence: list = []


class Comment(BaseModel):
    text: str


class GenerateRequest(BaseModel):
    # Which of the two sequences to build from. Never guessed: the record must
    # say which proposer produced the document.
    source: str = SOURCE_MODEL


def _normalized_view(draft) -> dict:
    """
    What the proposers actually read, beside what was submitted.

    Post: the fields that decide a trip, or an `error` naming why the record
          could not be read. `raw_record` is left out: the desk already shows
          the submitted record, and repeating it here would double every page.

    A normalisation that quietly falls back to its defaults is the fault WP1
    found, where an 8-day request built a 5-day trip and nothing said so. The
    reviewer can only see it if both readings are on the page (ws-03 6.4).
    """
    try:
        normalized = normalize_from_dict(
            draft.request_id or draft.draft_id, draft.request_row,
            source=draft.origin)
    except Exception as exc:
        return {"error": f"the request could not be read: {exc}"}
    return {
        "customer_name": normalized.customer_name,
        "customer_email": normalized.customer_email,
        "pax": normalized.pax,
        "day_count": normalized.day_count,
        "tour_type": normalized.tour_type,
        "hotel_tier": normalized.hotel_tier,
        "vehicle_type": normalized.vehicle_type,
        "requested_regions": normalized.requested_regions,
        "travel_month": normalized.travel_month,
        "travel_year": normalized.travel_year,
        "start_date": normalized.start_date.isoformat() if normalized.start_date else None,
        "special_notes": normalized.special_notes,
    }


def _draft_to_dict(draft) -> dict:
    """One draft as the desk reads it, with the two answers compared."""
    return {
        "draft_id": draft.draft_id,
        "request_id": draft.request_id,
        "origin": draft.origin,
        "request_row": draft.request_row,
        "normalized": _normalized_view(draft),
        "model_proposals_enabled": model_proposals_enabled(),
        "parse_warnings": draft.parse_warnings,
        "sequences": [vars(s) for s in draft.sequences],
        "comments": draft.comments,
        "agreement": sequences_agree(draft),
        "generated_from": draft.generated_from,
        "doc_url": draft.doc_url,
        "created_at": draft.created_at,
    }


def _request_pill(row: dict, drafts_by_key: dict) -> dict:
    """
    One worklist row as the desk's pill list reads it.

    Post: the fields a pill shows, plus the draft this request already has, or
          None. A request that was answered keeps its pill: the desk lists the
          work, and status is a fact about it rather than a filter on it
          (ws-03 6.1).
    """
    draft = drafts_by_key.get(row.get("key"))
    return {
        "key": row.get("key"),
        "source": row.get("source"),
        "status": row.get("status"),
        "name": row.get("name"),
        "email": row.get("email"),
        "summary": row.get("summary") or [],
        "next_action_date": row.get("next_action_date"),
        "created_at": row.get("created_at"),
        "risk": row.get("risk"),
        "draft_id": draft.draft_id if draft else None,
        "has_document": bool(draft and draft.doc_url),
    }


def setup_itinerary_desk_routes() -> APIRouter:
    router = APIRouter(prefix="/api/itinerary")

    @router.get("/requests")
    async def list_requests(request: Request, source: Optional[str] = None):
        """
        The Curated and Queue requests, whatever their status.

        Pre:  the Supabase credentials the worklist needs are configured.
        Post: every request of those two sources, newest work first, each
              carrying the draft it already has if there is one.

        Blame: an unreachable worklist is a configuration problem and answers
        502. The desk keeps no copy, so it has nothing to fall back on, and a
        stale local list would be worse than an honest failure (D14).
        """
        require_admin(request)
        from mcp_servers.ops_server import (
            OpsApiError,
            _fetch_merged_worklist,
            _project,
        )

        wanted = (source,) if source else REQUEST_SOURCES
        unknown = [s for s in wanted if s not in REQUEST_SOURCES]
        if unknown:
            raise HTTPException(422, f"not a request source: {', '.join(unknown)}")
        try:
            rows = await _fetch_merged_worklist()
        except OpsApiError as exc:
            raise HTTPException(502, str(exc)) from exc

        drafts_by_key = {d.request_id: d for d in iter_drafts() if d.request_id}
        pills = [_request_pill(row, drafts_by_key)
                 for row in _project(rows, "full", None, None)
                 if row.get("source") in wanted]
        return {"count": len(pills), "sources": list(wanted), "requests": pills}

    @router.post("/drafts/from-request")
    async def open_worklist_request(request: Request, body: WorklistRequest):
        """
        Start a thread for one worklist request, or return the one it has.

        Pre:  `key` is "curated:<id>" or "queue:<row_id>".
        Post: a draft holding the raw submitted record, with the rules answer
              already on it. The record is read from Supabase and never written
              back (invariant 2.4).

        Blame: a key naming a source that carries no trip is a caller error and
        answers 422. A key that resolves to no row answers 404.
        """
        require_admin(request)
        from mcp_servers.ops_server import OpsApiError, _fetch_full_record

        if ":" not in body.key:
            raise HTTPException(422, "key must be 'source:source_id'")
        source, source_id = body.key.split(":", 1)
        if source not in REQUEST_SOURCES:
            raise HTTPException(422, f"not a request source: {source}")
        try:
            record = await _fetch_full_record(source, source_id)
        except OpsApiError as exc:
            raise HTTPException(502, str(exc)) from exc
        if record is None:
            raise HTTPException(404, f"no request for {body.key}")

        # The raw submitted record, not the worklist's composed summary. The
        # normalizer already reads both shapes and picks by `source`, so nothing
        # here maps fields — a second mapper would drift from it.
        try:
            normalized = normalize_from_dict(body.key, record, source=source)
        except Exception as exc:
            raise HTTPException(422, f"the request could not be read: {exc}") from exc

        draft = open_draft(record, origin=ORIGIN_SHEET, request_id=body.key,
                           parse_warnings=normalized.parse_warnings)
        if not any(s.source == SOURCE_RULES for s in draft.sequences):
            try:
                draft = add_sequence(draft.draft_id,
                                     propose_by_rules(normalized, active_day_templates()))
            except Exception as exc:
                logger.exception("the rules proposer failed")
                raise HTTPException(502, f"the rules proposer failed: {exc}") from exc
        return _draft_to_dict(draft)

    @router.get("/drafts")
    async def list_drafts(request: Request):
        require_admin(request)
        drafts = [_draft_to_dict(d) for d in iter_drafts()]
        return {"count": len(drafts), "drafts": drafts}

    @router.get("/drafts/{draft_id}")
    async def get_draft(request: Request, draft_id: str):
        require_admin(request)
        draft = load(draft_id)
        if draft is None:
            raise HTTPException(404, "no such draft")
        return _draft_to_dict(draft)

    @router.post("/drafts")
    async def open_request(request: Request, body: RequestRow):
        """
        Start a thread for a request, or return the one it already has.

        The rules answer is produced here and once only. It is deterministic, so
        a second run would repeat it, and the thread reads against a fixed
        second opinion.
        """
        require_admin(request)
        try:
            normalized = normalize_from_dict(draft_id_for(body.row), body.row, source=body.origin)
        except Exception as exc:
            raise HTTPException(422, f"the request could not be read: {exc}") from exc

        draft = open_draft(body.row, origin=body.origin,
                           parse_warnings=normalized.parse_warnings)
        if not any(s.source == SOURCE_RULES for s in draft.sequences):
            try:
                draft = add_sequence(draft.draft_id,
                                     propose_by_rules(normalized, active_day_templates()))
            except Exception as exc:
                logger.exception("the rules proposer failed")
                raise HTTPException(502, f"the rules proposer failed: {exc}") from exc
        return _draft_to_dict(draft)

    @router.post("/drafts/{draft_id}/comment")
    async def record_comment(request: Request, draft_id: str, body: Comment):
        """
        Save a comment without asking anything for a new answer.

        Pre:  the draft exists and the text is not empty.
        Post: the comment is on the thread with `rule_state` set to new.

        Separate from the model route because feedback is worth keeping whether
        or not a model may run. With the proposer off (D17), this is the only
        way a comment reaches the judged rule book at all.
        """
        require_admin(request)
        try:
            draft = add_comment(draft_id, body.text)
        except DraftError as exc:
            raise HTTPException(409, str(exc)) from exc
        return _draft_to_dict(draft)

    @router.post("/drafts/{draft_id}/model")
    async def propose_with_model(request: Request, draft_id: str,
                                 body: Optional[Comment] = None):
        """
        Ask the model for a sequence, optionally about a comment.

        A comment is recorded first, then the model answers with the previous
        sequence and the comment in front of it. The rules answer never moves.
        """
        require_admin(request)
        draft = load(draft_id)
        if draft is None:
            raise HTTPException(404, "no such draft")

        comment = (body.text if body else "") or ""
        if comment.strip():
            try:
                draft = add_comment(draft_id, comment)
            except DraftError as exc:
                raise HTTPException(409, str(exc)) from exc

        previous = getattr(draft.latest.get(SOURCE_MODEL), "day_codes", [])
        normalized = normalize_from_dict(draft.draft_id, draft.request_row, source=draft.origin)
        try:
            sequence = await propose_by_model(
                normalized, active_day_templates(),
                comment=comment.strip(), previous=previous)
        except ModelProposalsDisabled as exc:
            # 409, not 502. The endpoint is reachable and the desk is working;
            # the owner has chosen not to send request text to it. The comment
            # above is already recorded, so nothing the reviewer typed is lost.
            raise HTTPException(409, str(exc)) from exc
        except ProposalError as exc:
            raise HTTPException(502, str(exc)) from exc
        return _draft_to_dict(add_sequence(draft_id, sequence))

    @router.post("/drafts/{draft_id}/generate")
    async def generate(request: Request, draft_id: str, body: GenerateRequest):
        """
        Build the document from the sequence you chose.

        This renders a Google Doc, so it runs only when asked. The record names
        the proposer whose sequence produced it.
        """
        require_admin(request)
        from services.itinerary.generator import execute_generation

        draft = load(draft_id)
        if draft is None:
            raise HTTPException(404, "no such draft")
        if body.source not in (SOURCE_MODEL, SOURCE_RULES):
            raise HTTPException(422, f"unknown source: {body.source}")
        chosen = draft.latest.get(body.source)
        if chosen is None or not chosen.day_codes:
            raise HTTPException(409, f"the {body.source} proposer has no sequence yet")

        normalized = normalize_from_dict(draft.draft_id, draft.request_row,
                                         source=draft.origin)
        try:
            built = execute_generation(normalized, day_codes=list(chosen.day_codes))
        except Exception as exc:
            logger.exception("generation failed")
            raise HTTPException(502, f"the document was not generated: {exc}") from exc

        if built.status != "success":
            return {"ok": False, "errors": [built.error_message or "generation failed"],
                    **_draft_to_dict(draft)}

        draft.generated_from = body.source
        draft.doc_url = built.doc_url or ""
        save(draft)
        return {"ok": True, "warnings": [], **_draft_to_dict(draft)}

    @router.get("/comments")
    async def list_comments(request: Request, rule_state: Optional[str] = None):
        """
        The feedback the judged rule book has not read yet.

        Pre:  `rule_state` is one of RULE_STATES, or absent for all of them.
        Post: comments oldest draft first, each naming the draft it sits on.
              A comment written before this field existed reads as `new`.

        Blame: an unknown state is a caller error and answers 422 rather than
        an empty list, which would read as "nothing to do".
        """
        require_admin(request)
        if rule_state is not None and rule_state not in RULE_STATES:
            raise HTTPException(
                422, f"rule_state must be one of {', '.join(RULE_STATES)}")
        comments = list(iter_comments(rule_state))
        return {"count": len(comments), "rule_state": rule_state,
                "comments": comments}

    @router.post("/comments/{draft_id}/{comment_id}")
    async def record_comment_verdict(request: Request, draft_id: str,
                                     comment_id: str, body: CommentVerdict):
        """
        Record what became of one comment, so it leaves the queue.

        Pre:  the draft holds a comment with this id.
        Post: that comment carries the new state. Nothing else on the draft
              changes, and the comment's text is never rewritten — it is
              evidence for the rule it produced.
        """
        require_admin(request)
        try:
            draft = set_comment_rule_state(draft_id, comment_id, body.rule_state)
        except DraftError as exc:
            raise HTTPException(404, str(exc)) from exc
        return _draft_to_dict(draft)

    @router.get("/rules")
    async def list_rules(request: Request):
        """
        Both rule books, kept apart.

        Post: the counted book and the judged book, each with its own summary.
              A reader sees which is which, because a judged rule carries a
              comment where a counted one carries a denominator (D16).
        """
        require_admin(request)
        from services.offers.rule_book import (
            BOOK_COUNTED, book_summary, iter_judged_rules, iter_rules,
            judged_summary)

        counted = [asdict(r) for r in iter_rules(BOOK_COUNTED)]
        judged = [asdict(r) for r in iter_judged_rules()]
        return {
            "counted": {"summary": book_summary(BOOK_COUNTED), "rules": counted},
            "judged": {"summary": judged_summary(), "rules": judged},
        }

    @router.post("/rules/judged")
    async def accept_judged_rule(request: Request, body: JudgedRuleDraft):
        """
        Accept a rule drafted from one comment, and take that comment off the
        queue.

        Pre:  the draft holds a comment with this id, and the statement is not
              empty. The owner's accept is this request; nothing writes a judged
              rule on its own (invariant 1.4's shape).
        Post: the rule is in the judged book with its corpus verdict, and the
              comment reads `drafted`.

        Blame: the rule is written before the comment moves, and its id comes
        from the comment, so a failure between the two leaves the comment
        queued and a retry overwrites the same rule rather than adding a second.
        """
        require_admin(request)
        from services.offers.rule_book import (
            JudgedRule, RuleBookError, load_judged_rule, rule_id_for_comment,
            save_judged_rule)

        draft = load(body.draft_id)
        if draft is None:
            raise HTTPException(404, "no such draft")
        comment = next((c for c in draft.comments
                        if c.get("comment_id") == body.comment_id), None)
        if comment is None:
            raise HTTPException(404, f"no comment {body.comment_id} on {body.draft_id}")

        try:
            save_judged_rule(JudgedRule(
                rule_id=rule_id_for_comment(body.comment_id),
                statement=body.statement,
                comment_id=body.comment_id,
                comment_text=comment.get("text") or "",
                draft_id=draft.draft_id,
                request_id=draft.request_id,
                corrected_sequence=list(body.corrected_sequence or []),
                family=body.family,
                subject=body.subject,
            ))
        except RuleBookError as exc:
            raise HTTPException(422, str(exc)) from exc

        set_comment_rule_state(body.draft_id, body.comment_id, RULE_STATE_DRAFTED)
        stored = load_judged_rule(rule_id_for_comment(body.comment_id))
        return {"ok": True, "rule": asdict(stored)}

    @router.get("/templates")
    async def list_active_codes(request: Request):
        """The codes a proposal may use. Inactive rows never appear."""
        require_admin(request)
        rows = active_day_templates()
        return {"count": len(rows),
                "codes": [{"code": code,
                           "title": field_of(row, "title"),
                           "city": field_of(row, "city"),
                           "overnight_city": field_of(row, "overnight_city"),
                           "region": field_of(row, "region")}
                          for code, row in sorted(rows.items())]}

    return router

