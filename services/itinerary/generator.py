"""
services/itinerary/generator.py

Drives the vendored itinerary pipeline: validation, quote calculation, and
Google Doc creation.

The pipeline used to be imported across a filesystem path from a separate
WebOperationsBilW checkout, so odysseus could not run without that checkout
present. It now lives in `services/itinerary/pipeline` (ws-03 decision B1).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from services.itinerary.models import (
    NormalizedRequest,
    ItineraryPreviewResult,
    ItineraryGenerationResult,
)
from services.itinerary.matcher import find_best_route, region_coverage
from services.itinerary.binder import bind_route_to_templates

logger = logging.getLogger(__name__)

def _ensure_pipeline_imported():
    """
    Bind the vendored pipeline's entry points.

    Post: a dict of the callables the rest of this module uses, or None if the
          package itself is broken.

    The dict shape and the lazy re-binding at each use site are kept from the
    old path-based bridge, which could legitimately find nothing. Vendoring
    makes absence a packaging bug rather than a configuration state, so a
    failure here is now worth a stack trace rather than a warning.
    """
    try:
        from services.itinerary.pipeline.models import TourRequest
        from services.itinerary.pipeline.app_core import (
            build_default_request,
            check_request,
            generate_document,
            load_runtime_data,
        )
        from services.itinerary.pipeline.loader import load_all_templates, load_pricing
    except Exception:
        logger.exception("vendored itinerary pipeline failed to import")
        return None
    return {
        "TourRequest": TourRequest,
        "check_request": check_request,
        "generate_document": generate_document,
        "build_default_request": build_default_request,
        "load_runtime_data": load_runtime_data,
        "load_all_templates": load_all_templates,
        "load_pricing": load_pricing,
    }


_PIPELINE = _ensure_pipeline_imported()


def load_templates() -> dict[str, Any]:
    global _PIPELINE
    if not _PIPELINE:
        _PIPELINE = _ensure_pipeline_imported()
    if _PIPELINE:
        try:
            return _PIPELINE["load_all_templates"]()
        except Exception as e:
            logger.error(f"Failed to load templates from pipeline: {e}")
    return {}


def build_tour_request(
    req: NormalizedRequest,
    bound_codes: list[str],
    doc_name: Optional[str] = None,
    exchange_rate: float = 1310.0,
) -> Any:
    global _PIPELINE
    if not _PIPELINE:
        _PIPELINE = _ensure_pipeline_imported()
    if not _PIPELINE:
        raise RuntimeError("services.itinerary.pipeline failed to import.")

    TourRequest = _PIPELINE["TourRequest"]

    single_rooms = 1 if req.pax == 1 else 0
    double_rooms = req.pax // 2 if req.pax > 1 else (0 if single_rooms == 1 else 1)
    if req.pax > 1 and req.pax % 2 != 0:
        single_rooms += 1

    clean_name = f"BilWeekend - {req.customer_name} ({len(bound_codes)} Days)" if not doc_name else doc_name

    return TourRequest(
        doc_name=clean_name,
        day_codes=bound_codes,
        start_date=req.start_date,
        tour_type=req.tour_type,
        num_people=req.pax,
        single_rooms=single_rooms,
        double_rooms=double_rooms,
        hotel_tier=req.hotel_tier,
        selected_vehicle=req.vehicle_type,
        guide_days_override=None,
        transport_days_override=None,
        include_transfers=True,
        include_shrine_help=False,
        include_food=False,
        food_tier=None,
        apply_markup=True,
        markup_percent=0.20,
        exchange_rate=exchange_rate,
        group_sizes=[],
        foc_per_group=1,
        group_vehicle="VIP_BUS" if req.tour_type == "group" else req.vehicle_type,
        sgl_supplement=400,
        apply_office_markup=True,
        office_markup_percent=0.20,
        apply_margin_markup=False,
        margin_markup_percent=0.0,
    )


def _format_quote(q: Any, hotel_tier: str = "3star") -> dict:
    if not q:
        return {}
    if isinstance(q, dict):
        return q
    tier = str(hotel_tier or "3star").lower()
    if "5" in tier:
        total = getattr(q, "final_total_5star", 0.0)
        pp = getattr(q, "per_person_5star", 0.0)
        hotel = getattr(q, "accommodation_5star", 0.0)
    elif "4" in tier:
        total = getattr(q, "final_total_4star", 0.0)
        pp = getattr(q, "per_person_4star", 0.0)
        hotel = getattr(q, "accommodation_4star", 0.0)
    else:
        total = getattr(q, "final_total_3star", 0.0)
        pp = getattr(q, "per_person_3star", 0.0)
        hotel = getattr(q, "accommodation_3star", 0.0)

    return {
        "total_usd": round(float(total), 2),
        "per_person_usd": round(float(pp), 2),
        "hotel_total_usd": round(float(hotel), 2),
        "non_hotel_subtotal_usd": round(float(getattr(q, "non_accommodation_subtotal", 0.0)), 2),
        "num_days": getattr(q, "num_days", 0),
        "num_nights": getattr(q, "num_nights", 0),
    }


def preview_itinerary(req: NormalizedRequest) -> ItineraryPreviewResult:
    global _PIPELINE
    if not _PIPELINE:
        _PIPELINE = _ensure_pipeline_imported()
    templates = load_templates()
    route, match_score = find_best_route(req)

    if not route:
        return ItineraryPreviewResult(
            key=req.key,
            matched_route_id="",
            matched_route_name="No matching route found",
            confidence_score=0.0,
            confidence_level="low",
            requested_day_count=req.day_count,
            delivered_day_count=0,
            bound_day_codes=[],
            coverage_gaps=["Route corpus is empty or no match could be identified."],
            calendar_warnings=[],
            estimated_quote=None,
            can_generate_document=False,
            validation_errors=["No matching route."],
        )

    bound_codes, gap_notes = bind_route_to_templates(route, templates, req.requested_regions)
    reg_cov = region_coverage(req, route)

    confidence_level = "high" if (match_score >= 0.65 and reg_cov > 0.6) else ("moderate" if match_score >= 0.4 else "low")

    estimated_quote = None
    cal_warnings: list[str] = []
    val_errors: list[str] = []
    can_generate = False

    if bound_codes and _PIPELINE:
        try:
            tour_req = build_tour_request(req, bound_codes)
            check_res = _PIPELINE["check_request"](tour_req)
            val_errors = check_res.get("errors", [])
            cal_warnings = check_res.get("warnings", [])
            can_generate = check_res.get("ok", False)

            pricing = _PIPELINE["load_pricing"]()
            from src.calculator import calculate_quote
            from src.builder import build_itinerary
            built_days = build_itinerary(tour_req, templates)
            q = calculate_quote(tour_req, built_days, pricing)
            if q:
                estimated_quote = _format_quote(q, req.hotel_tier)
        except Exception as e:
            logger.warning(f"Error during preview calculation: {e}")
            val_errors.append(f"Preview calculation notice: {e}")

    return ItineraryPreviewResult(
        key=req.key,
        matched_route_id=route.id,
        matched_route_name=route.source_file.replace(".docx", "").replace("_", " ").title(),
        confidence_score=match_score,
        confidence_level=confidence_level,
        requested_day_count=req.day_count,
        delivered_day_count=len(bound_codes),
        bound_day_codes=bound_codes,
        coverage_gaps=gap_notes,
        calendar_warnings=cal_warnings,
        estimated_quote=estimated_quote,
        can_generate_document=can_generate or (len(bound_codes) > 0 and not val_errors),
        validation_errors=val_errors,
    )


def execute_generation(req: NormalizedRequest) -> ItineraryGenerationResult:
    global _PIPELINE
    if not _PIPELINE:
        _PIPELINE = _ensure_pipeline_imported()
    preview = preview_itinerary(req)

    if not preview.bound_day_codes:
        return ItineraryGenerationResult(
            key=req.key,
            status="error",
            preview=preview,
            error_message="No day-codes could be bound for this request.",
        )

    if not _PIPELINE:
        return ItineraryGenerationResult(
            key=req.key,
            status="error",
            preview=preview,
            error_message="services.itinerary.pipeline failed to import.",
        )

    try:
        tour_req = build_tour_request(req, preview.bound_day_codes)
        gen_res = _PIPELINE["generate_document"](tour_req)

        if not gen_res.get("ok"):
            errs = gen_res.get("errors", ["Document rendering failed."])
            return ItineraryGenerationResult(
                key=req.key,
                status="error",
                preview=preview,
                error_message="; ".join(errs),
            )

        doc_url = gen_res.get("doc_url")
        doc_id = gen_res.get("doc_id")
        raw_quote = gen_res.get("quote")
        quote_summary = _format_quote(raw_quote, req.hotel_tier) if raw_quote else None

        return ItineraryGenerationResult(
            key=req.key,
            status="success",
            doc_id=doc_id,
            doc_url=doc_url,
            quote=quote_summary,
            preview=preview,
        )
    except Exception as exc:
        logger.exception(f"Document generation failed for {req.key}: {exc}")
        return ItineraryGenerationResult(
            key=req.key,
            status="error",
            preview=preview,
            error_message=str(exc),
        )
