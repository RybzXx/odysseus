"""routes/curated/itinerary_desk_routes.py

The itinerary desk: a request on the left, two proposed day-code sequences on
the right, and a comment that asks the model to answer again.

The model proposes and the vendored rules propose, on every request. Neither is
authoritative, so a disagreement is shown rather than resolved here.

Nothing on this surface writes to the operations sheet. A document is generated
only when it is asked for, because generation renders a Google Doc.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.middleware import require_admin

from services.curated.drafts import (
    ORIGIN_SHEET,
    ORIGIN_TYPED,
    SOURCE_MODEL,
    SOURCE_RULES,
    DraftError,
    add_comment,
    add_sequence,
    iter_drafts,
    load,
    open_draft,
    save,
    sequences_agree,
)
from services.curated.normalize import normalize_row
from services.curated.propose_sequence import (
    ProposalError,
    active_day_templates,
    propose_by_model,
    propose_by_rules,
)

logger = logging.getLogger(__name__)


class RequestRow(BaseModel):
    # The column dict normalize_row already reads. One shape serves a pasted
    # request and a fetched sheet row alike.
    row: dict
    origin: str = ORIGIN_TYPED


class Comment(BaseModel):
    text: str


class GenerateRequest(BaseModel):
    # Which of the two sequences to build from. Never guessed: the record must
    # say which proposer produced the document.
    source: str = SOURCE_MODEL


def _draft_to_dict(draft) -> dict:
    """One draft as the desk reads it, with the two answers compared."""
    return {
        "draft_id": draft.draft_id,
        "request_id": draft.request_id,
        "origin": draft.origin,
        "request_row": draft.request_row,
        "parse_warnings": draft.parse_warnings,
        "sequences": [vars(s) for s in draft.sequences],
        "comments": draft.comments,
        "agreement": sequences_agree(draft),
        "generated_from": draft.generated_from,
        "doc_url": draft.doc_url,
        "created_at": draft.created_at,
    }


def setup_itinerary_desk_routes() -> APIRouter:
    router = APIRouter(prefix="/api/itinerary")

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
            normalized = normalize_row(body.row, 0)
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
        normalized = normalize_row(draft.request_row, 0)
        try:
            sequence = await propose_by_model(
                normalized, active_day_templates(),
                comment=comment.strip(), previous=previous)
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
        from services.curated.request_builder import build_request
        from services.itinerary.pipeline.app_core import generate_document

        draft = load(draft_id)
        if draft is None:
            raise HTTPException(404, "no such draft")
        if body.source not in (SOURCE_MODEL, SOURCE_RULES):
            raise HTTPException(422, f"unknown source: {body.source}")
        chosen = draft.latest.get(body.source)
        if chosen is None or not chosen.day_codes:
            raise HTTPException(409, f"the {body.source} proposer has no sequence yet")

        normalized = normalize_row(draft.request_row, 0)
        try:
            tour = build_request(normalized, list(chosen.day_codes),
                                 draft.request_id, _exchange_rate())
            built = generate_document(tour)
        except Exception as exc:
            logger.exception("generation failed")
            raise HTTPException(502, f"the document was not generated: {exc}") from exc

        if not built.get("ok"):
            return {"ok": False, "errors": built.get("errors", []),
                    "warnings": built.get("warnings", []), **_draft_to_dict(draft)}

        draft.generated_from = body.source
        draft.doc_url = built.get("doc_url") or ""
        save(draft)
        return {"ok": True, "warnings": built.get("warnings", []),
                **_draft_to_dict(draft)}

    @router.get("/templates")
    async def list_active_codes(request: Request):
        """The codes a proposal may use. Inactive rows never appear."""
        require_admin(request)
        rows = active_day_templates()
        return {"count": len(rows),
                "codes": [{"code": code,
                           "title": row.get("title", ""),
                           "city": row.get("city", ""),
                           "overnight_city": row.get("overnight_city", ""),
                           "region": row.get("region", "")}
                          for code, row in sorted(rows.items())]}

    return router


def _exchange_rate() -> float:
    """
    Post: IQD per 1 USD, from the pipeline's own pricing data.

    Blame: a missing or zero rate is a data fault, not a caller fault, and it
    raises rather than pricing a tour at an invented rate.
    """
    from services.itinerary.pipeline.loader import load_pricing

    pricing = load_pricing()
    settings_block = (pricing or {}).get("settings") or {}
    rate = float(settings_block.get("exchange_rate") or 0)
    if rate <= 0:
        raise HTTPException(503, "no exchange rate is configured in the pricing data")
    return rate
