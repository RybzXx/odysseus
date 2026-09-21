"""Share an operator's saved itinerary through New Operations pricing. No model calls."""
from dataclasses import asdict, replace
import os

import httpx

from services.itinerary.group_quote import GroupQuoteOptions, PAYING_BANDS
from services.itinerary.normalizer import normalize_from_dict, request_kind
from services.itinerary.pipeline.loader import load_all_templates


def workspace_request(draft, options):
    basis = draft.group_quote_basis or {}
    latest = draft.sequences[-1] if draft.sequences else None
    codes = list(basis.get("day_codes") or getattr(latest, "day_codes", []) or [])
    normalized = normalize_from_dict(draft.request_id or draft.draft_id, draft.request_row, source=request_kind(draft.request_id))
    staff_codes = draft.request_row.get('_staff_route_codes')
    if staff_codes:
        codes = list(staff_codes)
    else:
        from services.itinerary.day_preferences import preferred_day_codes
        codes, _ = preferred_day_codes(codes, normalized)
    templates = load_all_templates()
    if not codes or any(code not in templates for code in codes):
        raise ValueError("A complete itinerary is required before sharing.")
    selected = []
    for index, code in enumerate(codes):
        day = templates[code]
        changes = basis.get("template_overrides", {}).get(code, {})
        allowed = {"title", "city", "overnight_city", "full_text", "included_sites", "pricing_tags"}
        if set(changes) - allowed:
            raise ValueError("An unsupported itinerary override cannot be shared.")
        day = replace(day, **changes)
        if index == 0 and basis.get("arrival_rest_only"):
            day = replace(day, title="Arrival and rest", full_text="Airport reception and hotel transfer. Rest without scheduled sightseeing.",
                          included_sites=[], pricing_tags=[tag for tag in day.pricing_tags if tag not in ("guide_day", "transport_day")])
        # A repeated code can have a different arrival treatment. Keep each occurrence distinct.
        day = replace(day, code=f"{code}_DAY_{index + 1}")
        selected.append(asdict(day))
    start_date = basis.get("start_date") or (normalized.start_date.isoformat() if normalized.start_date else None)
    title = basis.get("title") or basis.get("label") or draft.request_row.get("Name") or draft.request_row.get("name") or draft.request_id or draft.draft_id
    return {
        "external_id": f"odysseus:{draft.draft_id}", "document_url": draft.doc_url or None,
        "day_templates": selected,
        "request": {
            "doc_name": str(title), "source_key": draft.request_id, "day_codes": [day["code"] for day in selected],
            "start_date": start_date, "tour_type": "group", "hotel_tier": basis.get("hotel_tier") or normalized.hotel_tier,
            "group_sizes": list(PAYING_BANDS), "group_count_basis": "paying", "foc_per_group": 1,
            "group_vehicle": "TOYOTA_COASTER", "compare_group_vehicles": True,
            "office_markup_percent": options.office_markup_percent, "margin_markup_percent": options.margin_markup_percent,
            "apply_office_markup": True, "apply_margin_markup": True,
            "sgl_supplement": 0, "sgl_supplement_override": options.single_supplement_override,
            "omit_final_night": options.omit_final_night, "append_departure_day": True,
        },
    }


async def share_draft(draft, options: GroupQuoteOptions):
    base, token = os.environ.get("NEWOPS_API_URL", "").rstrip("/"), os.environ.get("NEWOPS_API_TOKEN", "")
    from src.ops_hub import hub_config, _post
    if not base or not token or hub_config() is None:
        return {"ok": False, "error": "Team sharing requires NEWOPS_API_URL, NEWOPS_API_TOKEN, OPS_API_BASE_URL, and OPS_AGENT_TOKEN."}
    try:
        body = workspace_request(draft, options)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.post(base + "/api/operations/quote", json=body, headers={"Authorization": f"Bearer {token}"})
        if response.status_code != 200:
            return {"ok": False, "error": "New Operations could not price this itinerary. Check its catalogue and connection."}
        return await _post("/api/agent/ops/itineraries", response.json())
    except (ValueError, httpx.HTTPError):
        return {"ok": False, "error": "The itinerary could not be shared. The saved draft is unchanged."}
