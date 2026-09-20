"""Price saved operations variants without replacing the submitted request."""
from dataclasses import asdict, replace
from datetime import date
import hashlib
import json
import math

from pydantic import BaseModel, ConfigDict, Field

from services.itinerary.pipeline.app_core import build_default_request, check_request
from services.itinerary.pipeline.builder import build_itinerary, count_hotel_nights_by_city, count_transport_days, count_guide_days
from services.itinerary.pipeline.calculator import calculate_quote
from services.itinerary.pipeline.loader import load_all_templates, load_pricing


class GroupQuoteOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    omit_final_night: bool = True
    office_markup_percent: float = Field(default=10, ge=0, le=100)
    margin_markup_percent: float = Field(default=20, ge=0, le=100)
    single_supplement_override: float | None = Field(default=None, ge=0, le=10000)


PAYING_BANDS = ((8, 9), (10, 11), (12, 13), (14, 14))
VEHICLES = ("TOYOTA_COASTER", "VIP_BUS")


def quote_draft(draft, options: GroupQuoteOptions, *, templates=None, pricing=None):
    """Return both vehicle estimates. Never mutate the draft or catalogue."""
    templates = dict(load_all_templates() if templates is None else templates)
    pricing = load_pricing() if pricing is None else pricing
    basis = draft.group_quote_basis or {}
    latest = draft.sequences[-1] if draft.sequences else None
    codes = list(basis.get("day_codes") or getattr(latest, "day_codes", []) or [])
    if not codes or any(code not in templates for code in codes):
        raise ValueError("A complete itinerary with known day codes is required for pricing.")
    for code, changes in basis.get("template_overrides", {}).items():
        if code not in codes:
            raise ValueError("A pricing override refers to a day outside this itinerary.")
        allowed = {"title", "city", "overnight_city", "full_text", "included_sites", "pricing_tags"}
        if set(changes) - allowed:
            raise ValueError("The saved operations variant contains an unsupported override.")
        templates[code] = replace(templates[code], **changes)

    from services.itinerary.normalizer import normalize_from_dict, request_kind
    normalized = normalize_from_dict(draft.request_id or draft.draft_id, draft.request_row,
                                     source=request_kind(draft.request_id))
    req = build_default_request(1310)
    req.doc_name = "Group itinerary estimate"
    req.day_codes = codes
    req.start_date = date.fromisoformat(basis["start_date"]) if basis.get("start_date") else normalized.start_date
    req.hotel_tier = basis.get("hotel_tier") or normalized.hotel_tier
    req.tour_type = "group"
    req.group_sizes = [(paying + 1, paying + 1) for paying in range(8, 15)]
    req.foc_per_group = 1
    req.office_markup_percent = options.office_markup_percent
    req.margin_markup_percent = options.margin_markup_percent
    req.single_supplement_override = options.single_supplement_override
    req.arrival_rest_only = bool(basis.get("arrival_rest_only", False))
    req.omit_final_night = options.omit_final_night
    req.append_departure_day = True
    last = templates[codes[-1]]
    if options.omit_final_night and not (last.overnight_city and "hotel_night" in last.pricing_tags):
        raise ValueError("The final day has no included hotel night to omit. Keep the existing departure option.")
    built = build_itinerary(req, templates)

    # A missing rate must never silently become a free service.
    def rate(value, label, *, positive=False):
        if not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0 or (positive and value == 0):
            raise ValueError(f"Missing or invalid operations price: {label}.")
    for city in count_hotel_nights_by_city(built):
        rates = pricing.get("hotel_tiers", {}).get(city, {}).get(req.hotel_tier, {})
        for key in ("single", "double", "team_fee"):
            rate(rates.get(key), f"{city} {req.hotel_tier} {key}", positive=key != "team_fee")
    for vehicle in VEHICLES:
        rate(pricing.get("_transport_by_code", {}).get(vehicle, {}).get("daily_rate_usd"), vehicle, positive=True)
    if count_guide_days(built):
        rate(pricing.get("settings", {}).get("guide_daily_rate_usd"), "guide", positive=True)
    settings = pricing.get("settings", {})
    rate(settings.get("airport_transfer_per_person_usd", settings.get("airport_transfer_flat_usd")), "airport transfers", positive=True)
    for day in built:
        for site in day.template.included_sites:
            ticket = pricing.get("_tickets_by_code", {}).get(site)
            if not ticket or not ticket.get("active", True):
                raise ValueError(f"Missing or inactive entry price: {site}.")
            for key in ("price_per_person", "price_flat"):
                rate(ticket.get(key, 0), f"{site} {key}")
    warnings = list(basis.get("warnings", []))
    warnings.append("Planning estimate. Confirm supplier rates and operating arrangements before issuing an offer.")
    if options.omit_final_night:
        warnings.append("Final tour and airport transfer are on the same day. Confirm a flight that allows the full tour and airport check-in.")
    results = {}
    for vehicle in VEHICLES:
        req.group_vehicle = vehicle
        checked = check_request(req, templates=templates, pricing=pricing, built_days=built)
        if checked["errors"]:
            raise ValueError(" ".join(checked["errors"]))
        warnings.extend(checked["warnings"])
        results[vehicle] = calculate_quote(req, built, pricing)
    rows = []
    for lower, upper in PAYING_BANDS:
        row = {"paying_min": lower, "paying_max": upper, "foc": 1}
        for vehicle in VEHICLES:
            # Odd groups need another double room. Check every size in the band.
            row[vehicle] = max(r.price_per_person for r in results[vehicle].group_rows
                               if lower <= r.min_pax - r.foc_count <= upper)
        rows.append(row)
    source = {"templates": [asdict(templates[c]) for c in codes], "pricing": pricing, "basis": basis}
    return {
        "draft_id": draft.draft_id, "options": options.model_dump(),
        "basis_label": basis.get("label") or "Latest proposed itinerary",
        "basis_is_operations_variant": bool(basis),
        "num_days": len(built), "num_nights": sum(count_hotel_nights_by_city(built).values()),
        "guide_days": count_guide_days(built), "transport_days": count_transport_days(built),
        "hotel_tier": req.hotel_tier, "nights_by_city": count_hotel_nights_by_city(built),
        "multiplier": round((1 + options.office_markup_percent / 100) * (1 + options.margin_markup_percent / 100), 6),
        "rows": rows, "single_supplement": results[VEHICLES[0]].group_rows[0].sgl_supplement,
        "vehicle_daily_rates": {v: pricing["_transport_by_code"][v]["daily_rate_usd"] for v in VEHICLES},
        "days": [{"number": d.day_number, "date": str(d.date) if d.date else None,
                  "code": d.template.code, "title": d.template.title, "text": d.template.full_text,
                  "overnight_city": d.template.overnight_city} for d in built],
        "warnings": list(dict.fromkeys(warnings)),
        "source_hash": hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest(),
    }
