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
        from services.itinerary.pipeline.builder import build_itinerary
        from services.itinerary.pipeline.calculator import calculate_quote
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
        # Bound here like every other entry point. These two were still
        # imported from `src.` at their use site, which is where the pipeline
        # lived before it was vendored, so every preview lost its quote to a
        # ModuleNotFoundError the caller swallowed as a notice.
        "build_itinerary": build_itinerary,
        "calculate_quote": calculate_quote,
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
    from services.itinerary.pipeline.config import DEFAULT_MARKUP_PCT, DEFAULT_MARGIN_PCT, DEFAULT_GROUP_SIZES

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
        markup_percent=DEFAULT_MARKUP_PCT,
        exchange_rate=exchange_rate,
        group_sizes=list(DEFAULT_GROUP_SIZES) if req.tour_type == "group" else [],
        foc_per_group=1,
        group_vehicle="VIP_BUS" if req.tour_type == "group" else req.vehicle_type,
        sgl_supplement=400,
        apply_office_markup=True,
        office_markup_percent=DEFAULT_MARKUP_PCT,
        apply_margin_markup=True,
        margin_markup_percent=DEFAULT_MARGIN_PCT,
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
        "tour_type": getattr(q, "tour_type", "individual"),
        "group_rows": [vars(row).copy() for row in getattr(q, "group_rows", [])],
        "office_markup_percent": getattr(q, "office_markup_percent", 0),
        "margin_markup_percent": getattr(q, "margin_markup_percent", 0),
        "total_usd": round(float(total), 2),
        "per_person_usd": round(float(pp), 2),
        "hotel_total_usd": round(float(hotel), 2),
        "non_hotel_subtotal_usd": round(float(getattr(q, "non_accommodation_subtotal", 0.0)), 2),
        "num_days": getattr(q, "num_days", 0),
        "num_nights": getattr(q, "num_nights", 0),
    }


def preview_itinerary(req: NormalizedRequest, day_codes: Optional[list[str]] = None, *, expected_plan=None) -> ItineraryPreviewResult:
    """Check and price the exact sequence. Never render or transmit a document."""
    from services.itinerary.candidates import build_candidates
    from services.itinerary.sequence_check import check_sequence
    from services.itinerary.resolved_plan import resolve_plan, stale_plan_errors
    templates = load_templates()
    candidates = build_candidates(req, templates, ceiling=1) if day_codes is None else None
    candidate = candidates.candidates[0] if candidates and candidates.candidates else None
    codes = list(day_codes if day_codes is not None else candidate.day_codes if candidate else [])
    plan = candidate.plan if candidate and candidate.plan else resolve_plan(codes, templates, req)
    if expected_plan is not None:
        plan.issues.extend(stale_plan_errors(expected_plan, req, templates, codes))
        plan.issues.extend(expected_plan.get("issues", []))
        plan.references = expected_plan.get("references", [])
        plan.corpus_version = expected_plan.get("corpus_version", "")
        if not plan.issues:
            # Preserve source evidence only after versions and saved integrity pass.
            for day, saved in zip(plan.days, expected_plan.get("days", [])):
                day["evidence"] = saved["evidence"]
    checked = check_sequence(codes, plan.templates, start_date=req.start_date, normalized_request=req, plan=plan)
    errors = [f.statement for f in checked.faults]
    errors.extend(f"Unknown code: {code}" for code in checked.unknown_codes)
    errors.extend(checked.untested)
    warnings, quote, prepared = [], None, None
    pipeline_ok = False
    if codes and checked.is_clean and _PIPELINE:
        try:
            tour_req = build_tour_request(req, codes)
            pricing = _PIPELINE["load_pricing"]()
            days = _PIPELINE["build_itinerary"](tour_req, plan.templates)
            result = _PIPELINE["check_request"](tour_req, templates=plan.templates, pricing=pricing, built_days=days)
            errors.extend(result.get("errors", []))
            warnings.extend(result.get("warnings", []))
            pipeline_ok = bool(result.get("ok"))
            raw_quote = _PIPELINE["calculate_quote"](tour_req, days, pricing) if pipeline_ok else None
            quote = _format_quote(raw_quote, req.hotel_tier) if raw_quote else None
            prepared = {"request": tour_req, "templates": plan.templates, "pricing": pricing,
                        "built_days": days, "quote": raw_quote}

        except Exception as exc:
            errors.append(f"Pricing validation failed: {exc}")
            pipeline_ok = False
    return ItineraryPreviewResult(
        key=req.key, matched_route_id=candidate.route_id if candidate else "",
        matched_route_name=candidate.route_name if candidate else "Selected sequence",
        confidence_score=candidate.match_score if candidate else 0.0,
        confidence_level="high" if checked.is_clean else "low",
        requested_day_count=req.day_count, delivered_day_count=len(codes),
        bound_day_codes=codes, coverage_gaps=candidate.gap_notes if candidate else [],
        calendar_warnings=warnings, estimated_quote=quote,
        can_generate_document=checked.is_clean and pipeline_ok and not errors,
        validation_errors=list(dict.fromkeys(errors)), plan=plan.to_dict(), prepared=prepared)


def execute_generation(req: NormalizedRequest,
                       day_codes: Optional[list[str]] = None, *, expected_plan=None) -> ItineraryGenerationResult:
    """
    Build the document for one request.

    Pre:  `day_codes`, when given, is the sequence a reviewer chose. Every code
          must name an active template.
    Post: the document holds exactly that sequence. Without it, the matcher and
          the binder choose, as they always did.

    Blame: a caller that holds a chosen sequence and does not pass it gets an
    itinerary built from a different one, and nothing on the result would say
    so. That is why the argument exists.
    """
    global _PIPELINE
    if not _PIPELINE:
        _PIPELINE = _ensure_pipeline_imported()
    preview = preview_itinerary(req, day_codes=day_codes, expected_plan=expected_plan)
    if not preview.can_generate_document:
        return ItineraryGenerationResult(key=req.key, status="error", preview=preview,
            error_message="; ".join(preview.validation_errors) or "The itinerary is not ready for document generation.")

    if not (day_codes or preview.bound_day_codes):
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
        from services.itinerary.resolved_plan import stale_plan_errors, content_hash
        changes = stale_plan_errors(preview.plan, req, load_templates(), preview.bound_day_codes)
        if preview.prepared is None:
            changes.append("The validated execution plan is missing. Recalculate it.")
        elif content_hash(_PIPELINE["load_pricing"]()) != content_hash(preview.prepared["pricing"]):
            changes.append("Pricing changed after preview. Recalculate the itinerary.")
        if changes:
            return ItineraryGenerationResult(key=req.key, status="error", preview=preview,
                                             error_message="; ".join(changes))
        gen_res = _PIPELINE["generate_document"](preview.prepared["request"], prepared=preview.prepared)

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
