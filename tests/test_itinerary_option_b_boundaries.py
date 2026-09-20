"""Regression contracts for Option B pricing, documents, and source facts."""
from dataclasses import replace
from datetime import date
import json

import pytest

from services.itinerary.models import NormalizedRequest, RouteDay
from services.itinerary.pipeline.models import DayTemplate
from services.itinerary.resolved_plan import resolve_plan, stale_plan_errors


def request():
    return NormalizedRequest(key="boundary", source="curated", customer_name="Synthetic",
        day_count=1, pax=2, start_date=date(2026, 10, 6),
        requested_regions=["Central Iraq & Middle Euphrates"])


def rows(tags):
    return {"BG": DayTemplate(code="BG", title="Baghdad city tour", city="Baghdad",
        region="Central Iraq & Middle Euphrates", overnight_city="Baghdad",
        full_text="Visit Baghdad.", included_sites=[], pricing_tags=tags,
        active=True, needs_review=False, internal_notes="")}


def test_desk_and_pipeline_default_use_the_same_markup_units():
    from services.itinerary.generator import build_tour_request
    from services.itinerary.pipeline.app_core import build_default_request
    from services.itinerary.pipeline.calculator import _effective_multiplier
    desk = build_tour_request(request(), ["BG"])
    pipeline = build_default_request(desk.exchange_rate)
    assert _effective_multiplier(desk) == _effective_multiplier(pipeline)


def test_excluded_hotel_is_not_promised_by_document_assembly(monkeypatch):
    from services.itinerary import generator
    from services.itinerary.generator import build_tour_request
    from services.itinerary.pipeline.builder import build_itinerary
    from services.itinerary.pipeline.calculator import calculate_quote
    from services.itinerary.pipeline.loader import load_pricing
    from services.itinerary.pipeline.assembler import assemble
    req = request()
    catalogue = rows([])
    plan = resolve_plan(["BG"], catalogue, req)
    assert plan.days[0]["accommodation"] == "excluded"
    monkeypatch.setattr(generator, "load_templates", lambda: catalogue)
    preview = generator.preview_itinerary(req, ["BG"], expected_plan=plan.to_dict())
    assert preview.can_generate_document, preview.validation_errors
    tour = build_tour_request(req, ["BG"])
    built = build_itinerary(tour, plan.templates)
    pricing = load_pricing()
    quote = calculate_quote(tour, built, pricing)
    assert quote.accommodation_3star == 0
    sections = assemble(tour, built, quote, {}, pricing)
    includes = next(s.content["items"] for s in sections if s.section_type == "includes")
    assert not any("Accommodation in hotels" in item for item in includes)
    assert not any(s.section_type == "hotel_options" for s in sections)


def test_unknown_accommodation_stays_unknown():
    plan = resolve_plan(["BG"], rows(None), request())
    assert plan.days[0]["accommodation"] == "unknown"
    assert any("accommodation inclusion is unknown" in issue for issue in plan.issues)


@pytest.mark.parametrize("text,role", [
    ("Transfer to Erbil airport.", "departure"),
    ("Visit Erbil. Return to Erbil.", "day_trip"),
    ("No transfer to Erbil airport is included. Return to Erbil.", "day_trip"),
    ("Optional departure from Erbil airport.", "unknown"),
    ("We may transfer to Erbil airport.", "unknown"),
    ("We do not return to Erbil.", "unknown"),
    ("We don't transfer to Erbil airport.", "unknown"),
    ("No hotel is included. Transfer to Erbil airport.", "departure"),
    ("30th May 2024. Transfer to Erbil airport.", "departure"),
    ("May 30 transfer to Erbil airport.", "departure"),
    ("Tour Erbil.", "unknown"),
])
def test_source_role_requires_positive_departure_evidence(text, role):
    from services.itinerary.day_facts import source_day_facts
    facts = source_day_facts(RouteDay(1, "", text), "Erbil")
    assert facts["role"] == role


@pytest.mark.parametrize("number", [
    0, -1, None, "1.5",
    1.5, True,
])
def test_malformed_source_day_numbers_never_become_usable(number, tmp_path, monkeypatch):
    from services.offers import offer_store
    from services.itinerary.route_corpus import load_reference_pool
    monkeypatch.setattr(offer_store, "OFFER_CORPUS_DIR", str(tmp_path))
    record = tmp_path / "synthetic"
    record.mkdir()
    (record / "offer.json").write_text(json.dumps({"message_id": "synthetic",
        "sent_at": "2026-09-01T12:00:00+00:00", "days": [
            {"day": number, "overnight_city": "Baghdad", "text": "Visit Baghdad."}]}), encoding="utf-8")
    pool = load_reference_pool(force_reload=True)
    assert pool["record_count"] == 1
    assert pool["counts"]["usable"] == 0


@pytest.mark.parametrize("change", ["city", "site", "arrival", "departure", "date", "pax"])
def test_changed_request_requirements_expire_a_saved_plan(change):
    req, catalogue = request(), rows(["hotel_night"])
    saved = resolve_plan(["BG"], catalogue, req).to_dict()
    changes = {"city": {"required_cities": ["Mosul"]}, "site": {"required_sites": ["NA_UR"]},
        "arrival": {"arrival_city": "Basra"}, "departure": {"departure_city": "Erbil"},
        "date": {"start_date": date(2026, 10, 7)}, "pax": {"pax": 3}}
    assert stale_plan_errors(saved, replace(req, **changes[change]), catalogue, ["BG"])


@pytest.mark.parametrize("codes", [[], ["BG", "BG"], ["UNKNOWN"]])
def test_changed_code_count_or_identity_expires_plan(codes):
    req, catalogue = request(), rows(["hotel_night"])
    saved = resolve_plan(["BG"], catalogue, req).to_dict()
    assert stale_plan_errors(saved, req, catalogue, codes)


@pytest.mark.parametrize("percent", [0, 10, 17.5])
@pytest.mark.parametrize("margin", [0, 20])
def test_configured_markup_controls_quote_and_plan_version(percent, margin, monkeypatch):
    from services.itinerary.generator import build_tour_request
    from services.itinerary.pipeline import config
    from services.itinerary.pipeline.calculator import _effective_multiplier
    req, catalogue = request(), rows(["hotel_night"])
    monkeypatch.setattr(config, "DEFAULT_MARKUP_PCT", percent)
    monkeypatch.setattr(config, "DEFAULT_MARGIN_PCT", margin)
    tour = build_tour_request(req, ["BG"])
    assert _effective_multiplier(tour) == pytest.approx((1 + percent / 100) * (1 + margin / 100))
    saved = resolve_plan(["BG"], catalogue, req).to_dict()
    monkeypatch.setattr(config, "DEFAULT_MARKUP_PCT", percent + 1)
    assert any("Pricing changed" in error for error in stale_plan_errors(saved, req, catalogue, ["BG"]))
    monkeypatch.setattr(config, "DEFAULT_MARKUP_PCT", percent)
    monkeypatch.setattr(config, "DEFAULT_MARGIN_PCT", margin + 1)
    assert any("Pricing changed" in error for error in stale_plan_errors(saved, req, catalogue, ["BG"]))


@pytest.mark.parametrize("no_hotels", [False, True])
def test_mixed_stays_only_promise_and_override_included_nights(no_hotels):
    from services.itinerary.generator import build_tour_request
    from services.itinerary.pipeline.builder import build_itinerary, count_hotel_nights_by_city
    from services.itinerary.pipeline.assembler import _build_includes_content, _build_hotel_options_content, _compute_custom_acc
    from types import SimpleNamespace
    catalogue = rows(["hotel_night"])
    catalogue["OWNBG"] = replace(catalogue["BG"], code="OWNBG", pricing_tags=[])
    catalogue["OWNMO"] = replace(catalogue["BG"], code="OWNMO", city="Mosul", overnight_city="Mosul", pricing_tags=[])
    tour = build_tour_request(request(), ["BG", "OWNBG", "OWNMO"])
    tour.no_hotels_mode = no_hotels
    tour.selected_include_keys = ["accommodation"]
    built = build_itinerary(tour, catalogue)
    assert count_hotel_nights_by_city(built) == {"Baghdad": 1}
    quote = SimpleNamespace(num_days=3)
    includes = _build_includes_content(tour, quote, built)["items"]
    assert includes == ([] if no_hotels else ["Accommodation in hotels for nights 1 only, as per the selection."])
    options = _build_hotel_options_content(tour, built, quote, {})
    assert all("Mosul" not in line for tier in options["tier_blocks"] for line in tier["lines"])
    assert _compute_custom_acc(built, {"Baghdad": "HOTEL"}, 0, 0, 1,
                               {"HOTEL": {"double_rate": 100}}) == 100


@pytest.mark.parametrize("number", [1, "1", " 1 "])
def test_source_day_number_preserves_supported_integer_forms(number):
    from services.itinerary.route_corpus import _source_day_number
    assert _source_day_number(number) == 1
