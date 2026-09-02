"""
routes/operations/itinerary_routes.py

REST API endpoints for previewing, generating, and staging automated itineraries and customer replies.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.middleware import require_admin
from src.auth_helpers import require_user
from mcp_servers.ops_server import (
    _fetch_full_record,
    _stage_change,
    _write_note,
    _config,
    OpsApiError,
)
from services.itinerary import (
    normalize_from_dict,
    preview_itinerary,
    execute_generation,
    compose_email_reply,
    compose_whatsapp_reply,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/operations/itinerary", tags=["Operations Itinerary"])


class GenerateRequest(BaseModel):
    key: str
    stage: bool = True


class StageReplyRequest(BaseModel):
    key: str
    doc_url: Optional[str] = None
    email_draft: Optional[dict] = None
    whatsapp_draft: Optional[str] = None
    status: Optional[str] = "Replied"
    rationale: Optional[str] = "Custom itinerary proposal generated and reply drafted"


async def _resolve_record_from_key(key: str) -> tuple[str, str, dict]:
    if ":" not in key:
        raise HTTPException(422, "key must be in 'source:source_id' format")
    source, source_id = key.split(":", 1)
    if _config() is None:
        raise HTTPException(503, "Supabase is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).")
    try:
        record = await _fetch_full_record(source, source_id)
    except OpsApiError as e:
        raise HTTPException(502, f"Failed to fetch record: {e}")

    if not record:
        raise HTTPException(404, f"No record found for key '{key}'")
    return source, source_id, record


@router.get("/preview")
async def get_itinerary_preview(request: Request, key: str):
    require_admin(request)
    source, _, record = await _resolve_record_from_key(key)
    norm_req = normalize_from_dict(key, record, source=source)
    preview = preview_itinerary(norm_req)

    email_draft = compose_email_reply(norm_req, preview, doc_url=None, quote=preview.estimated_quote)
    whatsapp_draft = compose_whatsapp_reply(norm_req, preview, doc_url=None, quote=preview.estimated_quote)

    return {
        "preview": preview.to_dict(),
        "draft_email": email_draft,
        "draft_whatsapp": whatsapp_draft,
        "normalized_request": {
            "name": norm_req.customer_name,
            "email": norm_req.customer_email,
            "phone": norm_req.customer_phone,
            "pax": norm_req.pax,
            "day_count": norm_req.day_count,
            "regions": norm_req.requested_regions,
            "hotel_tier": norm_req.hotel_tier,
            "vehicle": norm_req.vehicle_type,
            "start_date": norm_req.start_date.isoformat() if norm_req.start_date else None,
            "travel_month": norm_req.travel_month,
        },
    }


@router.post("/generate")
async def generate_itinerary_endpoint(request: Request, body: GenerateRequest):
    require_admin(request)
    user = require_user(request) or "operator"
    source, _, record = await _resolve_record_from_key(body.key)
    norm_req = normalize_from_dict(body.key, record, source=source)

    gen_res = execute_generation(norm_req)
    if gen_res.status != "success":
        raise HTTPException(500, f"Generation failed: {gen_res.error_message}")

    email_draft = compose_email_reply(norm_req, gen_res.preview, doc_url=gen_res.doc_url, quote=gen_res.quote)
    whatsapp_draft = compose_whatsapp_reply(norm_req, gen_res.preview, doc_url=gen_res.doc_url, quote=gen_res.quote)

    gen_res.draft_email = email_draft
    gen_res.draft_whatsapp = whatsapp_draft

    staged_id = None
    if body.stage:
        try:
            note_text = (
                f"Generated {gen_res.preview.delivered_day_count}-Day itinerary Doc: {gen_res.doc_url}\n"
                f"Matched Route: {gen_res.preview.matched_route_name} (Confidence: {gen_res.preview.confidence_level})\n"
                f"Quote: ${gen_res.quote.get('total_usd', 0):,.2f} USD"
            )
            _write_note(body.key, author=f"itinerary:{user}", text=note_text)

            stage_out = _stage_change(
                key=body.key,
                patch={"status": "In Progress"},
                expected_updated_at=None,
                author=f"user:{user}",
                rationale=f"Itinerary generated: {gen_res.doc_url}",
            )
            staged_id = stage_out.get("id")
            gen_res.staged_change_id = staged_id
        except Exception as e:
            logger.warning(f"Could not auto-stage generated itinerary note: {e}")

    return gen_res.to_dict()


@router.post("/stage-reply")
async def stage_reply_endpoint(request: Request, body: StageReplyRequest):
    require_admin(request)
    user = require_user(request) or "operator"

    email_subj = (body.email_draft or {}).get("subject", "Custom Itinerary Proposal")
    note_text = f"Drafted Reply: '{email_subj}'"
    if body.doc_url:
        note_text += f"\nAttached Doc: {body.doc_url}"
    _write_note(body.key, author=f"reply:{user}", text=note_text)

    patch = {}
    if body.status:
        patch["status"] = body.status

    try:
        stage_out = _stage_change(
            key=body.key,
            patch=patch,
            expected_updated_at=None,
            author=f"user:{user}",
            rationale=body.rationale or "Drafted customer reply",
        )
        return {"ok": True, "staged": stage_out}
    except OpsApiError as e:
        raise HTTPException(422, str(e))
