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
    ProposalError,
    analyse_catalogue_gap,
    iter_offers,
    iter_proposals,
    load_template_texts,
    load_templates,
    propose_new_templates,
    propose_revisions,
    queue_summary,
    record_verdict,
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
from services.offers.proposals import save as save_proposal

logger = logging.getLogger(__name__)


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
        drafted = (propose_revisions(offers, report, template_texts, corpus=corpus)
                   + propose_new_templates(report, template_texts, corpus=corpus))
        for proposal in drafted:
            save_proposal(proposal)
        summary = summarise_gap(report, len(offers), corpus=corpus)
        save_gap_summary(summary)
        return {"drafted": len(drafted), "queue": queue_summary(), "gap": summary}

    @router.get("/proposals")
    async def list_proposals(request: Request, status: Optional[str] = None,
                             kind: Optional[str] = None):
        require_admin(request)
        if status and status not in (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED):
            raise HTTPException(422, f"unknown status: {status}")
        if kind and kind not in (KIND_NEW, KIND_REVISION):
            raise HTTPException(422, f"unknown kind: {kind}")

        template_texts = load_template_texts()
        # One live fingerprint for the whole queue. Judging each proposal on its
        # own would stat the corpus once per proposal for an answer that cannot
        # change inside one request.
        live = corpus_fingerprint()
        items = []
        for proposal in iter_proposals(status):
            if kind is not None and proposal.kind != kind:
                continue
            item = _proposal_to_dict(proposal, template_texts)
            # The state alone, not the whole comparison. The live half is the
            # same for every proposal and is returned once as "corpus" below;
            # repeating both halves 257 times added 56 KB to a 615 KB response.
            item["provenance"] = corpus_provenance(proposal.corpus, live)["state"]
            items.append(item)
        return {"count": len(items), "queue": queue_summary(),
                "corpus": live, "proposals": items}

    @router.get("/proposals/{proposal_id}")
    async def get_proposal(request: Request, proposal_id: str):
        require_admin(request)
        proposal = load_proposal(proposal_id)
        if proposal is None:
            raise HTTPException(404, "no such proposal")
        return _proposal_to_dict(proposal, load_template_texts())

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
