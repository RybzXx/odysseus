"""routes/offers/offers_routes.py

Human review surface over the day-template catalogue gap.

The catalogue is what the itinerary builder can express; the sent-offer corpus
is what was actually written. This panel shows where the two disagree and lets
a reviewer decide, one proposal at a time, before anything reaches the
catalogue sheet.

Reads the corpus and the catalogue from disk. It never writes to Google Sheets:
approving a proposal records a verdict, and applying approved proposals is a
separate deliberate step (ws-03 WP1.5).
"""

import difflib
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.middleware import require_admin

from services.offers import (
    KIND_NEW,
    KIND_REVISION,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_RETIRED,
    FREQUENCY_RARE,
    FREQUENCY_RECURRING,
    ProposalError,
    analyse_catalogue_gap,
    catalogue_regions,
    iter_offers,
    iter_proposals,
    load_template_texts,
    load_templates,
    propose_new_templates,
    propose_revisions,
    queue_summary,
    record_verdict,
    retire_undrafted,
)
from services.offers.offer_store import (
    corpus_fingerprint,
    corpus_provenance,
    offers_of_message,
)
from services.offers.gap_report import load_summary as load_gap_summary
from services.offers.gap_report import save_summary as save_gap_summary
from services.offers.gap_report import summarise as summarise_gap
from services.offers.proposals import load as load_proposal
from services.offers.proposals import is_ready_to_push, record_suggestion, revise_approved
from services.offers.proposals import save as save_proposal

logger = logging.getLogger(__name__)


class Revision(BaseModel):
    fields: dict


class ApplyRequest(BaseModel):
    # A write to the catalogue must be asked for in words. The default plans and
    # writes nothing, so a request that forgets the field cannot change the sheet.
    write: bool = False
    only: Optional[list] = None


class Verdict(BaseModel):
    status: str
    reviewer_note: str = ""
    edited_fields: Optional[dict] = None


def _word_diff(before: str, after: str) -> list:
    """
    The change between two texts, word by word.

    Post: [(op, words)] where op is "same", "added" or "removed". A reviewer
          reads a revision by its deviation, not by re-reading both sides —
          most revisions differ by a clause inside otherwise identical prose.
    """
    left, right = (before or "").split(), (after or "").split()
    parts = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, left, right, autojunk=False).get_opcodes():
        if op == "equal":
            parts.append(("same", " ".join(left[i1:i2])))
        else:
            if i1 != i2:
                parts.append(("removed", " ".join(left[i1:i2])))
            if j1 != j2:
                parts.append(("added", " ".join(right[j1:j2])))
    return parts


def _proposal_to_dict(proposal, template_texts: dict) -> dict:
    """One proposal plus what a reviewer needs to judge it without leaving the page."""
    current = None
    if proposal.kind == KIND_REVISION and proposal.target_code:
        current = template_texts.get(proposal.target_code)
    return {
        "proposal_id": proposal.proposal_id,
        "kind": proposal.kind,
        "status": proposal.status,
        "occurrences": proposal.occurrences,
        "weight": proposal.weight,
        "target_code": proposal.target_code,
        "current_text": current,
        "proposed_text": proposal.fields.get("full_text", ""),
        "overnight_city": proposal.fields.get("overnight_city", ""),
        "nearest_code": proposal.nearest_code,
        "nearest_score": proposal.nearest_score,
        "reordered_codes": proposal.reordered_codes,
        "diff": _word_diff(current, proposal.fields.get("full_text", "")) if current else [],
        "evidence_day_keys": proposal.evidence_day_keys,
        "internal_notes": proposal.fields.get("internal_notes", ""),
        "fields": proposal.fields,
        "frequency": proposal.frequency,
        "suggested": proposal.suggested,
        "ready_to_push": is_ready_to_push(proposal),
        "reviewer_note": proposal.reviewer_note,
        "created_at": proposal.created_at,
        "decided_at": proposal.decided_at,
    }


def setup_offers_routes() -> APIRouter:
    router = APIRouter(prefix="/api/offers")

    @router.get("/gap")
    async def get_catalogue_gap(request: Request):
        """
        Coverage of the catalogue as of the last time proposals were derived.

        Read, not recomputed. The analysis takes minutes over a full corpus —
        long enough that computing it per request timed the page out — and a
        fresh measurement beside a stale queue would show two different gaps
        with no way to tell which the proposals came from.
        """
        require_admin(request)
        summary = load_gap_summary()
        if summary is None:
            return {"measured": False,
                    "detail": "the gap has not been measured yet — re-derive from corpus"}
        # The figure is returned even when it is stale, and the provenance says
        # so beside it. Withholding it would hide the one number that tells a
        # reviewer how far the queue has drifted from the corpus.
        return {"measured": True,
                "provenance": corpus_provenance(summary.get("corpus")),
                **summary}

    @router.post("/proposals/rebuild")
    async def rebuild_proposals(request: Request):
        """
        Re-derive proposals from the current corpus and catalogue.

        Idempotent by construction: a proposal's id is its content, and one
        already carrying a verdict is left exactly as the reviewer left it.
        """
        require_admin(request)
        corpus = corpus_fingerprint()
        offers = list(iter_offers())
        if not offers:
            raise HTTPException(409, "the offer corpus is empty — recover it first")

        template_texts = load_template_texts()
        report = analyse_catalogue_gap(offers, template_texts)
        counts = {}
        drafted = (propose_revisions(offers, report, template_texts, corpus=corpus)
                   + propose_new_templates(report, template_texts, corpus=corpus,
                                           counts=counts))
        for proposal in drafted:
            save_proposal(proposal)
        retired = retire_undrafted(p.proposal_id for p in drafted)
        summary = summarise_gap(report, len(offers), corpus=corpus)
        save_gap_summary(summary)
        return {"drafted": len(drafted), "retired": retired, "patterns": counts,
                "queue": queue_summary(), "gap": summary}

    @router.get("/proposals")
    async def list_proposals(request: Request, status: Optional[str] = None,
                             kind: Optional[str] = None,
                             frequency: Optional[str] = None):
        require_admin(request)
        if status and status not in (STATUS_PENDING, STATUS_APPROVED,
                                     STATUS_REJECTED, STATUS_RETIRED):
            raise HTTPException(422, f"unknown status: {status}")
        if kind and kind not in (KIND_NEW, KIND_REVISION):
            raise HTTPException(422, f"unknown kind: {kind}")
        if frequency and frequency not in (FREQUENCY_RARE, FREQUENCY_RECURRING):
            raise HTTPException(422, f"unknown frequency: {frequency}")

        template_texts = load_template_texts()
        # One live fingerprint for the whole queue. Judging each proposal on its
        # own would stat the corpus once per proposal for an answer that cannot
        # change inside one request.
        live = corpus_fingerprint()
        items = []
        for proposal in iter_proposals(status, frequency=frequency):
            if kind is not None and proposal.kind != kind:
                continue
            item = _proposal_to_dict(proposal, template_texts)
            # The state alone, not the whole comparison. The live half is the
            # same for every proposal and is returned once as "corpus" below;
            # repeating both halves 257 times added 56 KB to a 615 KB response.
            item["provenance"] = corpus_provenance(proposal.corpus, live)["state"]
            items.append(item)
        # The regions the catalogue uses, sent once. The reviewer picks from
        # them rather than typing one, so a new row lands in a region the sheet
        # already knows.
        return {"count": len(items), "queue": queue_summary(),
                "corpus": live, "regions": catalogue_regions(), "proposals": items}

    @router.get("/proposals/{proposal_id}")
    async def get_proposal(request: Request, proposal_id: str):
        require_admin(request)
        proposal = load_proposal(proposal_id)
        if proposal is None:
            raise HTTPException(404, "no such proposal")
        return _proposal_to_dict(proposal, load_template_texts())

    @router.post("/proposals/{proposal_id}/suggest")
    async def suggest_row_for_proposal(request: Request, proposal_id: str):
        """
        Ask the configured model to complete the columns the draft leaves empty.

        The answer is stored as machine text under `suggested` and is never
        merged into the proposal's fields. Only the reviewer's accept moves a
        value across, through the verdict path.

        Blame: an unreachable model is reported as 502 and the card stays
        usable. A suggestion is an offer, never a requirement.
        """
        require_admin(request)
        from services.offers.suggest_row import SuggestionError, suggest_catalogue_row

        proposal = load_proposal(proposal_id)
        if proposal is None:
            raise HTTPException(404, "no such proposal")
        try:
            suggestion = await suggest_catalogue_row(
                proposal.fields.get("full_text", ""),
                proposal.fields.get("overnight_city", ""),
            )
        except SuggestionError as exc:
            raise HTTPException(502, str(exc)) from exc
        try:
            record_suggestion(proposal_id, suggestion)
        except ProposalError as exc:
            raise HTTPException(409, str(exc)) from exc
        return _proposal_to_dict(load_proposal(proposal_id), load_template_texts())

    @router.post("/proposals/{proposal_id}/verdict")
    async def decide_proposal(request: Request, proposal_id: str, body: Verdict):
        """Approve or reject one proposal, optionally with the reviewer's edits."""
        require_admin(request)
        try:
            proposal = record_verdict(
                proposal_id,
                body.status,
                reviewer_note=body.reviewer_note,
                edited_fields=body.edited_fields,
            )
        except ProposalError as exc:
            raise HTTPException(409, str(exc)) from exc
        return _proposal_to_dict(proposal, load_template_texts())

    @router.post("/proposals/{proposal_id}/revise")
    async def revise_approved_proposal(request: Request, proposal_id: str, body: Revision):
        """
        Fill or correct the catalogue columns of an approved row before it is
        written to the sheet.

        The verdict stands. Only the columns change, and only while the row has
        not reached the catalogue.
        """
        require_admin(request)
        try:
            revised = revise_approved(proposal_id, body.fields)
        except ProposalError as exc:
            raise HTTPException(409, str(exc)) from exc
        return _proposal_to_dict(revised, load_template_texts())

    @router.get("/evidence/{day_key:path}")
    async def get_evidence_day(request: Request, day_key: str):
        """
        The sent day a proposal cites, so a reviewer can read the original.

        Blame: an unknown key means the corpus was rebuilt under different ids,
        not that the proposal is invalid — hence 404 with that said plainly.
        """
        require_admin(request)
        # Only the offers from the message the key names, not the whole corpus.
        # A day key is "<message-id>#<day-number>", so the message is known and
        # the scan was reading all 335 records to find one day.
        message_id = day_key.rsplit("#", 1)[0]
        for offer in offers_of_message(message_id):
            for day in offer.days:
                if f"{offer.message_id}#{day.day_number}" == day_key:
                    return {
                        "day_key": day_key,
                        "subject": offer.subject,
                        "sent_at": offer.sent_at.isoformat() if offer.sent_at else None,
                        "attachment_name": offer.attachment_name,
                        "day_number": day.day_number,
                        "overnight_city": day.overnight_city,
                        "text": day.text,
                    }
        raise HTTPException(404, "no such day in the current corpus")

    @router.post("/apply")
    async def apply_to_catalogue(request: Request, body: ApplyRequest):
        """
        Plan, and on request write, the approved proposals into the templates tab.

        This is the only handler that changes the catalogue. It plans by default.
        The sheet id comes from the pipeline config and is never taken from the
        request, so no caller can aim this at another spreadsheet.

        Blame: a proposal approved without a code is reported as skipped, not
        written under a blank name. That is a review omission, not an error here.
        """
        require_admin(request)
        from services.itinerary.pipeline import config
        from services.offers.apply_to_sheet import apply_approved

        sheet_id = config.JSON_DB_SHEET_ID
        try:
            plan = apply_approved(sheet_id, dry_run=True, only=body.only)
            if not body.write:
                return plan
            if not plan["appends"] and not plan["updates"]:
                return plan
            # Planned again against the sheet as it is now. A row someone else
            # added between the two calls changes the plan, and writing the
            # older one would overwrite their work.
            return apply_approved(sheet_id, dry_run=False, only=body.only)
        except Exception as exc:
            logger.exception("catalogue write refused")
            raise HTTPException(502, f"the catalogue write did not run: {exc}") from exc

    @router.get("/templates")
    async def list_catalogue(request: Request):
        require_admin(request)
        templates = load_templates()
        return {
            "count": len(templates),
            "templates": [
                {
                    "code": code,
                    "title": data.get("title", ""),
                    "overnight_city": data.get("overnight_city", ""),
                    "region": data.get("region", ""),
                    "active": data.get("active", True),
                    "needs_review": data.get("needs_review", False),
                    "words": len((data.get("full_text") or "").split()),
                }
                for code, data in sorted(templates.items())
            ],
        }

    return router
