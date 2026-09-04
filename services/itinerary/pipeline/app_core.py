"""
BilWeekend — Core Application Flow
Shared generation logic used by both CLI and GUI entrypoints.
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import date

from services.itinerary.pipeline import config
from services.itinerary.pipeline import google_clients
from services.itinerary.pipeline.models import TourRequest
from services.itinerary.pipeline.loader import load_all_templates, load_pricing, load_general_info
from services.itinerary.pipeline.validator import validate
from services.itinerary.pipeline.builder import build_itinerary
from services.itinerary.pipeline.calculator import calculate_quote
from services.itinerary.pipeline.assembler import assemble, assemble_day_trips
from services.itinerary.pipeline.renderer import render
from services.itinerary.pipeline.logger import log_quote
from services.itinerary.pipeline import calendar_warnings


def load_credentials():
    """The shared service-account credentials, read from disk once per process."""
    return google_clients.credentials()


def review_messages(messages: list[str]) -> tuple[list[str], list[str]]:
    errors = [m for m in messages if m.startswith("ERROR:")]
    warnings = [m for m in messages if m.startswith("WARNING:")]
    return errors, warnings


def build_default_request(exchange_rate: float) -> TourRequest:
    return TourRequest(
        doc_name="",
        day_codes=[],
        start_date=None,
        tour_type="individual",
        num_people=1,
        single_rooms=0,
        double_rooms=1,
        hotel_tier="3star",
        selected_vehicle="SMALL_CAR",
        guide_days_override=None,
        transport_days_override=None,
        include_transfers=True,
        include_shrine_help=False,
        include_food=False,
        food_tier=None,
        apply_markup=True,
        markup_percent=config.DEFAULT_MARKUP_PCT,
        exchange_rate=exchange_rate,
        group_sizes=[],
        foc_per_group=1,
        group_vehicle="VIP_BUS",
        sgl_supplement=400,
        # Tkinter / CLI: only one markup level (office only, no margin)
        apply_office_markup=True,
        office_markup_percent=config.DEFAULT_MARKUP_PCT,
        apply_margin_markup=False,
        margin_markup_percent=0.0,
    )


def load_runtime_data():
    templates = load_all_templates()
    pricing = load_pricing()
    general_info = load_general_info()
    return templates, pricing, general_info


def check_request(request: TourRequest) -> dict:
    """
    Validates the request and returns warnings/errors without generating a document.
    Used by the GUI to prompt the author before committing to rendering.
    Returns: {"ok": bool, "errors": [...], "warnings": [...], "built_days": [...]}
    """
    templates, pricing, _ = load_runtime_data()

    pre_messages = validate(request, templates, pricing)
    pre_errors, _ = review_messages(pre_messages)
    if pre_errors:
        return {"ok": False, "errors": pre_errors, "warnings": [], "built_days": []}

    built_days = build_itinerary(request, templates)
    messages = validate(request, templates, pricing, built_days=built_days)
    errors, warnings = review_messages(messages)
    # Append calendar/religious/holiday warnings (never block generation)
    cal_warnings = calendar_warnings.check_itinerary(request, built_days)
    warnings += calendar_warnings.to_plain_strings(cal_warnings)
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "built_days": built_days,
        "calendar_warnings": cal_warnings,
    }


def generate_document(
    request: TourRequest,
    add_pricing: bool = True,
    include_breakdown_in_doc: bool = False,
    hotel_overrides: dict | None = None,
    triple_rooms: int = 0,
) -> dict:
    templates, pricing, general_info = load_runtime_data()

    # Build the itinerary first so validate() can use dated built_days
    # for weekday-conflict checks. A preliminary structural validation
    # (errors only) runs before build so unknown codes don't cause a KeyError.
    pre_messages = validate(request, templates, pricing)
    pre_errors, _ = review_messages(pre_messages)
    if pre_errors:
        return {
            "ok": False,
            "errors": pre_errors,
            "warnings": [],
            "doc_url": None,
            "doc_id": None,
            "quote": None,
            "built_days": [],
        }

    built_days = build_itinerary(request, templates)

    # Full validation with availability checks now that we have dated days
    messages = validate(request, templates, pricing, built_days=built_days)
    errors, warnings = review_messages(messages)
    # Calendar warnings are appended regardless of errors (never block generation)
    cal_warnings = calendar_warnings.check_itinerary(request, built_days)
    warnings += calendar_warnings.to_plain_strings(cal_warnings)
    if errors:
        return {
            "ok": False,
            "errors": errors,
            "warnings": warnings,
            "doc_url": None,
            "doc_id": None,
            "quote": None,
            "built_days": built_days,
            "calendar_warnings": cal_warnings,
        }

    quote = calculate_quote(request, built_days, pricing) if add_pricing else None

    creds = load_credentials()
    sections = assemble(
        request,
        built_days,
        quote,
        general_info,
        pricing,
        include_breakdown_in_doc=include_breakdown_in_doc,
        hotel_overrides=hotel_overrides or {},
        triple_rooms=triple_rooms,
    )
    doc_id = render(sections)
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

    if quote:
        log_quote(request, quote, doc_id)

    return {
        "ok": True,
        "errors": [],
        "warnings": warnings,
        "doc_url": doc_url,
        "doc_id": doc_id,
        "quote": quote,
        "built_days": built_days,
        "calendar_warnings": cal_warnings,
    }


def generate_day_trips_document(
    doc_name: str,
    trips: list,
    include_breakdown_in_doc: bool = False,
) -> dict:
    """
    Generate a single Google Doc containing multiple independent day-trip sections.

    Each element of `trips` must be a dict with:
        name             str
        request          TourRequest
        hotel_overrides  dict[str, str]  (may be empty)
        triple_rooms     int

    Returns:
        {"ok", "errors", "warnings", "doc_url", "doc_id",
         "trip_results": [{"name", "errors", "warnings", "quote", "built_days", "calendar_warnings"}]}
    """
    templates, pricing, general_info = load_runtime_data()

    all_errors: list[str] = []
    all_warnings: list[str] = []
    trip_results: list[dict] = []
    resolved_trips: list[dict] = []

    for trip in trips:
        name = trip["name"]
        request = trip["request"]
        hotel_overrides = trip.get("hotel_overrides") or {}
        triple_rooms = trip.get("triple_rooms", 0)

        # Structural pre-validation
        pre_msgs = validate(request, templates, pricing)
        pre_errors, _ = review_messages(pre_msgs)
        if pre_errors:
            all_errors.extend([f"[{name}] {e}" for e in pre_errors])
            trip_results.append({
                "name": name, "errors": pre_errors, "warnings": [],
                "quote": None, "built_days": [], "calendar_warnings": [],
            })
            continue

        built_days = build_itinerary(request, templates)
        msgs = validate(request, templates, pricing, built_days=built_days)
        errors, warnings = review_messages(msgs)
        cal_warns = calendar_warnings.check_itinerary(request, built_days)
        warnings += calendar_warnings.to_plain_strings(cal_warns)

        if errors:
            all_errors.extend([f"[{name}] {e}" for e in errors])
            all_warnings.extend([f"[{name}] {w}" for w in warnings])
            trip_results.append({
                "name": name, "errors": errors, "warnings": warnings,
                "quote": None, "built_days": built_days, "calendar_warnings": cal_warns,
            })
            continue

        all_warnings.extend([f"[{name}] {w}" for w in warnings])
        quote = calculate_quote(request, built_days, pricing)

        trip_results.append({
            "name": name, "errors": [], "warnings": warnings,
            "quote": quote, "built_days": built_days, "calendar_warnings": cal_warns,
        })
        resolved_trips.append({
            "name": name,
            "request": request,
            "built_days": built_days,
            "quote": quote,
            "hotel_overrides": hotel_overrides,
            "triple_rooms": triple_rooms,
        })

    if all_errors:
        return {
            "ok": False,
            "errors": all_errors,
            "warnings": all_warnings,
            "doc_url": None,
            "doc_id": None,
            "trip_results": trip_results,
        }

    creds = load_credentials()
    sections = assemble_day_trips(
        doc_name,
        resolved_trips,
        general_info,
        pricing,
        include_breakdown_in_doc=include_breakdown_in_doc,
    )
    doc_id = render(sections)
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

    # Log each trip individually so the quick-start history stays accurate
    for tr in trip_results:
        if tr["quote"] is not None:
            req = next(t["request"] for t in resolved_trips if t["name"] == tr["name"])
            log_quote(req, tr["quote"], doc_id)

    return {
        "ok": True,
        "errors": [],
        "warnings": all_warnings,
        "doc_url": doc_url,
        "doc_id": doc_id,
        "trip_results": trip_results,
    }
