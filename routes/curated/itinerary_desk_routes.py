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
from itertools import zip_longest
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.middleware import require_admin

from services.itinerary.drafts import (
    OPEN_REQUEST_ORIGINS,
    ORIGIN_SHEET,
    RULE_STATE_DRAFTED,
    RULE_STATES,
    draft_id_for,
    ORIGIN_TYPED,
    SOURCE_MODEL,
    SOURCE_RULES,
    DraftError,
    NOTE_SOURCE_MODEL,
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
from services.itinerary.conversation_reader import conversation_link_of
from services.itinerary.normalizer import (
    REQUEST_SOURCES,
    SOURCE_UNKNOWN,
    normalize_from_dict,
    request_kind,
)
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


# The worklist sources that carry a tour request are `normalizer.REQUEST_SOURCES`,
# imported above. Bookings and contacts are the other two, and neither describes
# a trip to build (ws-03 D14). One tuple, because the desk and the normalizer
# disagreeing about what a kind is called is how the kind got lost (D59).


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


class Note(BaseModel):
    # A machine note. Kept apart from a comment, because a comment is the raw
    # material of a judged rule and a note is not (ws-03 D33).
    text: str
    source: str = NOTE_SOURCE_MODEL


class CreateOffer(BaseModel):
    # Read the screenshots again rather than using the cached text. A cache
    # keyed on the Drive file id is right until somebody replaces the image
    # behind the id.
    force_read: bool = False


class ConversationEdit(BaseModel):
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
            source=request_kind(draft.request_id))
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
        "parse_warnings": normalized.parse_warnings,
        # Which of these the record did not state. A reviewer reading a value
        # cannot otherwise tell an answer from a default (ws-03 phase seven, D65).
        "defaulted_fields": normalized.defaulted_fields,
        "request_kind": normalized.source,
    }


def _staleness_of(draft, templates: dict) -> Optional[dict]:
    """
    Post: how far the stored rules sequence has drifted from what the rules
          answer today, or None when it has not drifted and None when nothing
          can be compared.

    Pre:  `templates` holds the active codes.
    Inv:  nothing is written. The stored sequence is the fixed second opinion a
          comment thread reads against, so recomputation compares and never
          replaces it (ws-03 phase seven, D58, WP32.2).

    The desk stores the rules answer once, when the draft opens, and shows it
    beside a check computed live. Six of the nine worklist drafts stored an
    empty sequence and none is empty on recomputation, so half the owner's
    comments describe sequences the code no longer produces.
    """
    stored = next((s for s in draft.sequences if s.source == SOURCE_RULES), None)
    if stored is None:
        return None
    try:
        normalized = normalize_from_dict(
            draft.request_id or draft.draft_id, draft.request_row,
            source=request_kind(draft.request_id))
        fresh = propose_by_rules(normalized, templates)
    except Exception:
        logger.exception("the rules proposal could not be recomputed for %s",
                         draft.draft_id)
        return None

    if list(fresh.day_codes) == list(stored.day_codes):
        return None
    differ = sum(1 for a, b in zip_longest(stored.day_codes, fresh.day_codes)
                 if a != b)
    return {
        "differs": differ,
        "stored_day_count": len(stored.day_codes),
        "fresh_day_count": len(fresh.day_codes),
        "fresh_day_codes": list(fresh.day_codes),
        "fresh_note": fresh.note,
        "statement": (f"proposed under an older rule set. The rules answer "
                      f"{len(fresh.day_codes)} day(s) today against the "
                      f"{len(stored.day_codes)} stored, and {differ} position(s) "
                      f"differ"),
    }


def _start_date_of(normalized_view: dict):
    """Post: the trip's first day as a date, or None when the request has none."""
    from datetime import date

    stamp = normalized_view.get("start_date")
    if not stamp:
        return None
    try:
        return date.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def _draft_to_dict(draft, templates: Optional[dict] = None) -> dict:
    """
    One draft as the desk reads it, with the two answers compared and each one
    checked.

    Pre:  `templates` maps a code to its live template row. A caller reading
          many drafts loads it one time and passes it, because the pipeline
          loader reads 60 files from disk on every call.
    Post: every sequence carries a `check` naming what is wrong with it, and
          `day_count` naming what the request asked for beside what the
          sequence answers.

    Blame: a check that cannot run records itself in `untested` rather than
    reporting a clean sequence. A sequence that raises inside the check keeps
    its codes and carries `check: None`, because a broken check must not hide
    the answer a reviewer came to read.
    """
    from services.itinerary.sequence_check import check_sequence, check_to_dict

    rows = active_day_templates() if templates is None else templates
    normalized = _normalized_view(draft)
    start_date = _start_date_of(normalized)
    stale = _staleness_of(draft, rows)

    sequences = []
    for sequence in draft.sequences:
        entry = vars(sequence).copy()
        try:
            entry["check"] = check_to_dict(check_sequence(
                sequence.day_codes, rows, start_date=start_date,
                request_row=draft.request_row,
                day_count=normalized.get("day_count") or 0))
        except Exception:
            logger.exception("the sequence check failed on %s", draft.draft_id)
            entry["check"] = None
        if sequence.source == SOURCE_RULES:
            entry["stale"] = stale
        sequences.append(entry)

    return {
        "draft_id": draft.draft_id,
        "request_id": draft.request_id,
        "origin": draft.origin,
        "request_row": draft.request_row,
        "normalized": normalized,
        "day_count": normalized.get("day_count"),
        "model_proposals_enabled": model_proposals_enabled(),
        # Live, not the copy the draft stored when it was opened. Seven of the
        # nine worklist drafts carried a warning about a region name the map
        # now resolves, and a reviewer read it as a request the catalogue could
        # not answer (ws-03 phase seven, WP32.5).
        "parse_warnings": normalized.get("parse_warnings", draft.parse_warnings),
        "stale": stale,
        "sequences": sequences,
        "comments": draft.comments,
        # What the machine noticed, kept apart from what a human said
        # (ws-03 D33). A note never reaches the comment queue.
        "notes": draft.notes,
        "agreement": sequences_agree(draft),
        # The runs that produced the sequences, newest first. Only the ids and
        # a summary: the record holds every prompt, and a list route that
        # returned all of them would send four prompts per draft to a page
        # showing eleven drafts (ws-03 D42).
        "run_ids": list(getattr(draft, "run_ids", []) or []),
        "runs": _run_summaries(draft),
        # The brief the newest run produced, so the desk renders the same card
        # the Operations modal renders (ws-03 D55). It is 1,427 bytes and it
        # sits in a run step, so a reader would otherwise open the run record
        # to see what the customer asked for.
        "brief": _newest_brief(draft),
        "conversation_link": conversation_link_of(draft.request_row),
        "generated_from": draft.generated_from,
        "doc_url": draft.doc_url,
        "created_at": draft.created_at,
    }


def _newest_brief(draft) -> Optional[dict]:
    """
    Post: the brief the newest run wrote, or None when no run wrote one.

    Pre:  the draft names its runs in `run_ids`, newest last.

    The brief lives in a run step's result, which is where the run record puts
    it. Reading it here spares every caller the run record, and it keeps one
    wire shape: `brief_to_dict` produced it and `briefCard.js` renders it.

    Blame: a run id that resolves to no record is skipped. A deleted record
    must not empty the card.
    """
    from services.itinerary.run_record import STEP_BRIEF
    from services.itinerary.run_record import load as load_run

    for run_id in reversed(list(getattr(draft, "run_ids", []) or [])):
        run = load_run(run_id)
        if run is None:
            continue
        step = run.step(STEP_BRIEF)
        if step is not None and step.result:
            return step.result
    return None


def _draft_row(draft, templates: Optional[dict] = None) -> dict:
    """
    One draft as a list renders it, and nothing more (ws-03 D57).

    Pre:  `templates` maps a code to its live template row, loaded once by the
          caller for the whole list.
    Post: the fields a queue row shows: which request, how many days it
          answers, what the newest sequence's check found, and whether a
          document exists. No sequence, no check body, no run.

    Blame: `_draft_to_dict` is the detail, and `GET /drafts/{id}` serves it.
    Measured 2026-09-08: the list route sent 51,646 bytes for 11 drafts, of
    which 10,178 bytes was one draft's sequences, to render one of them.
    """
    from services.itinerary.sequence_check import check_sequence

    rows = active_day_templates() if templates is None else templates
    newest = draft.latest
    chosen = newest.get(SOURCE_MODEL) or newest.get(SOURCE_RULES)
    day_codes = list(getattr(chosen, "day_codes", []) or [])

    faults = flags = unknown = 0
    if day_codes:
        try:
            normalized = _normalized_view(draft)
            check = check_sequence(
                day_codes, rows, start_date=_start_date_of(normalized),
                request_row=draft.request_row,
                day_count=normalized.get("day_count") or 0)
            faults, flags = len(check.faults), len(check.flags)
            # A code the catalogue does not hold is not a fault: the checker
            # blames the catalogue rather than the proposer (phase four). The
            # row must still say so, or a sequence of two invented codes reads
            # as "2 days, no faults" and looks like work that is finished.
            unknown = len(check.unknown_codes)
        except Exception:
            logger.exception("the row check failed on %s", draft.draft_id)

    return {
        "draft_id": draft.draft_id,
        "request_id": draft.request_id,
        "origin": draft.origin,
        "day_count": len(day_codes),
        "asked_days": _normalized_view(draft).get("day_count"),
        "fault_count": faults,
        "flag_count": flags,
        "unknown_code_count": unknown,
        # Runs whose record still exists. `run_ids` counts what the draft
        # names, and a deleted record leaves an id behind: the queue then
        # offered "has a run" for a draft whose detail pane showed none.
        "run_count": _readable_run_count(draft),
        "comment_count": len(draft.comments or []),
        "has_document": bool(draft.doc_url),
        "created_at": draft.created_at,
    }


def _readable_run_count(draft) -> int:
    """
    Post: how many of this draft's runs still have a record on disk.

    Blame: `_run_summaries` already skips a dangling id, so a count taken from
    `run_ids` disagrees with the pane that renders them. One number, one
    source.
    """
    from services.itinerary.run_record import load as load_run

    return sum(1 for run_id in (getattr(draft, "run_ids", []) or [])
               if load_run(run_id) is not None)


def _run_summaries(draft) -> list:
    """
    Post: one short row per run this draft produced, newest first.

    Blame: a run id that resolves to no record is skipped rather than raised.
    A deleted record must not empty the desk.
    """
    from services.itinerary.run_record import load as load_run

    summaries = []
    for run_id in reversed(list(getattr(draft, "run_ids", []) or [])):
        run = load_run(run_id)
        if run is None:
            continue
        summaries.append({
            "run_id": run.run_id,
            "statement": run.statement,
            "started_at": run.started_at,
            "is_complete": run.is_complete,
            "untested": run.untested,
            "failures": run.failures,
            "endpoints_reached": run.endpoints_reached,
        })
    return summaries


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
        "operator": row.get("operator"),
        "next_action_date": row.get("next_action_date"),
        "moderation": row.get("moderation"),
        "created_at": row.get("created_at"),
        # The desk stages a change of its own now, and `POST /api/operations/
        # stage` checks this against Supabase before it writes. Without it the
        # desk would have to stage with no expectation, which turns an
        # optimistic write into a blind one.
        "updated_at": row.get("updated_at"),
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

        drafts_by_key = {d.request_id: d
                         for d in iter_drafts(OPEN_REQUEST_ORIGINS) if d.request_id}
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
        """
        Every open draft, as a list row (ws-03 D57).

        Post: one short row per draft. A caller that needs a sequence, a check
              or a run asks `GET /drafts/{id}` for that one draft.

        Graded drafts are trips that were already sold, opened only so a read
        can be marked against them. They are not work on the desk.

        One template load for the whole list. The pipeline loader reads 60
        files from disk on every call.
        """
        require_admin(request)
        rows = active_day_templates()
        drafts = [_draft_row(d, rows) for d in iter_drafts(OPEN_REQUEST_ORIGINS)]
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
            normalized = normalize_from_dict(draft_id_for(body.row), body.row,
                                             source=SOURCE_UNKNOWN)
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

    @router.post("/drafts/{draft_id}/propose-again")
    async def propose_again(request: Request, draft_id: str):
        """
        Run the rules proposer again and put its answer on the thread.

        Pre:  the draft exists.
        Post: a new rules sequence sits on the thread with its own
              `proposed_at`. Every earlier sequence stays, with the comments
              made against it.

        Blame: the rules proposer is deterministic for one rule set, and the
        rule set changes. A draft opened before a change carries an answer the
        code no longer gives, and half the owner's comments of 2026-09-07
        describe such an answer. Overwriting would leave a comment reading
        against a sequence nobody can see, so this appends (ws-03 phase seven,
        D58, WP32.3).
        """
        require_admin(request)
        draft = load(draft_id)
        if draft is None:
            raise HTTPException(404, "no such draft")
        try:
            normalized = normalize_from_dict(
                draft.request_id or draft.draft_id, draft.request_row,
                source=request_kind(draft.request_id))
            fresh = propose_by_rules(normalized, active_day_templates())
        except Exception as exc:
            logger.exception("the rules proposer failed")
            raise HTTPException(502, f"the rules proposer failed: {exc}") from exc
        draft = add_sequence(draft.draft_id, fresh)
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
        normalized = normalize_from_dict(draft.draft_id, draft.request_row,
                                         source=request_kind(draft.request_id))
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

    @router.post("/drafts/{draft_id}/create-offer")
    async def create_offer_for_draft(request: Request, draft_id: str,
                                     body: Optional[CreateOffer] = None):
        """
        Button 1. Read the conversation, reason, choose an itinerary.

        Pre:  the draft exists.
        Post: a sealed run record, a `model` sequence on the draft, and layer
              3's note on `notes`. No Google Doc is built and Drive holds no
              new file (spec item 23.1).

        Blame: a layer the owner did not configure is a configuration state and
        not a failure. The run records it untested and finishes, because every
        conversation folder answered 404 until the owner shared them and a run
        that refused would refuse every request (ws-03 D43).
        """
        require_admin(request)
        from services.itinerary.offer_run import create_offer
        from services.itinerary.run_record import run_to_dict

        draft = load(draft_id)
        if draft is None:
            raise HTTPException(404, "no such draft")
        try:
            outcome = create_offer(draft, active_day_templates(),
                                   force_read=bool(body and body.force_read))
        except Exception as exc:
            logger.exception("the offer run failed")
            raise HTTPException(502, f"the offer run failed: {exc}") from exc

        from services.itinerary.candidates import candidate_set_to_dict
        from services.itinerary.request_brief import brief_to_dict

        return {
            "run": run_to_dict(outcome.run),
            "brief": brief_to_dict(outcome.brief) if outcome.brief else None,
            "candidates": (candidate_set_to_dict(outcome.candidate_set)
                           if outcome.candidate_set else None),
            "chosen": {
                "index": outcome.ranking.index if outcome.ranking else 0,
                "day_codes": list(outcome.chosen_codes),
                "reason": outcome.ranking.reason if outcome.ranking else "",
                "chose_by_default": (outcome.ranking.chose_by_default
                                     if outcome.ranking else True),
            },
            "review_note": outcome.review_note,
            **_draft_to_dict(outcome.draft),
        }

    @router.get("/runs/{run_id}")
    async def get_run(request: Request, run_id: str):
        """
        One run, with every prompt and every answer.

        This is the trace the desk holds and the Operations modal does not
        (ws-03 D44). A prompt carries the customer's own words, so it is served
        to an admin and never rendered in a document (invariant 3.3).
        """
        require_admin(request)
        from services.itinerary.run_record import load as load_run
        from services.itinerary.run_record import run_to_dict

        run = load_run(run_id)
        if run is None:
            raise HTTPException(404, "no such run")
        return run_to_dict(run)

    @router.get("/layers")
    async def list_layers(request: Request):
        """
        Whether each itinerary layer may run, and where it would send.

        Post: one row per layer, naming its switch and the endpoint it would
              reach. An unconfigured layer states the refusal rather than a
              blank, because a blank reads as "it works".
        """
        require_admin(request)
        from services.itinerary.layer_access import (
            MASTER_SWITCH,
            access_report,
            master_enabled,
        )

        return {"master_switch": MASTER_SWITCH, "master_enabled": master_enabled(),
                "layers": access_report()}

    @router.put("/conversations/{file_id}")
    async def edit_conversation_text(request: Request, file_id: str,
                                     body: ConversationEdit):
        """
        Record a human's own reading of one screenshot (ws-03 D46, item 17.5).

        Pre:  `file_id` is the Drive id of an image this desk has read.
        Post: the edit is stored and every later run uses it. The model's own
              text is kept beside it and never overwritten, because the pair is
              the evidence for how well the model reads.
        """
        require_admin(request)
        from services.itinerary.conversation_reader import (
            ConversationError,
            set_human_text,
        )

        try:
            extracted = set_human_text(file_id, body.text)
        except ConversationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"file_id": extracted.file_id, "text": extracted.text,
                "source": extracted.source, "at": extracted.at}

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
                                         source=request_kind(draft.request_id))
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

        # The reply drafts travel with the document, so the desk can finish the
        # request without a second surface. The Operations modal has returned
        # them since it was built; a reviewer who generated here had to open
        # Operations for the wording alone.
        from services.itinerary import compose_email_reply, compose_whatsapp_reply

        try:
            email_draft = compose_email_reply(normalized, built.preview,
                                              doc_url=built.doc_url,
                                              quote=built.quote)
            whatsapp_draft = compose_whatsapp_reply(normalized, built.preview,
                                                    doc_url=built.doc_url,
                                                    quote=built.quote)
        except Exception:
            # A document that exists is the result. A composer that raised is
            # worth reporting, and it must not lose the build that succeeded.
            logger.exception("the reply drafts could not be composed")
            email_draft, whatsapp_draft = None, ""

        return {"ok": True, "warnings": [],
                "draft_email": email_draft, "draft_whatsapp": whatsapp_draft,
                **_draft_to_dict(draft)}

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

    @router.post("/drafts/{draft_id}/note")
    async def record_note(request: Request, draft_id: str, body: Note):
        """
        Record a note the machine made, kept apart from the owner's comments.

        Pre:  the draft exists and the text is not empty.
        Post: the note is on `notes` with its time and its source. `comments` is
              untouched, so `GET /comments` still returns only what a human
              wrote (ws-03 D33).

        A note that repeats one already on the draft is not added again. The
        check runs on every read, and a list that grew each time would bury the
        note it was written to show.
        """
        require_admin(request)
        from services.itinerary.drafts import add_note

        try:
            draft = add_note(draft_id, body.text, body.source)
        except DraftError as exc:
            raise HTTPException(409, str(exc)) from exc
        return _draft_to_dict(draft)

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

