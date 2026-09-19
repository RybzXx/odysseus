"""Adversarial contracts for the deployed Option B release.

Strict expected failures retain confirmed defects without changing production.
Use --runxfail to reproduce the underlying failures.
"""
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


@pytest.mark.xfail(strict=True, reason="B-T01: desk ignores configured markup percentage")
def test_desk_and_pipeline_default_use_the_same_markup_units():
    from services.itinerary.generator import build_tour_request
    from services.itinerary.pipeline.app_core import build_default_request
    from services.itinerary.pipeline.calculator import _effective_multiplier
    desk = build_tour_request(request(), ["BG"])
    pipeline = build_default_request(desk.exchange_rate)
    assert _effective_multiplier(desk) == _effective_multiplier(pipeline)


@pytest.mark.xfail(strict=True, reason="B-T02: document promises excluded accommodation")
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


@pytest.mark.xfail(strict=True, reason="B-T03: null tags silently mean excluded accommodation")
def test_unknown_accommodation_stays_unknown():
    plan = resolve_plan(["BG"], rows(None), request())
    assert plan.days[0]["accommodation"] == "unknown"
    assert any("accommodation inclusion is unknown" in issue for issue in plan.issues)


@pytest.mark.parametrize("text,role", [
    ("Transfer to Erbil airport.", "departure"),
    ("Visit Erbil. Return to Erbil.", "day_trip"),
    pytest.param("No transfer to Erbil airport is included. Return to Erbil.", "day_trip",
        marks=pytest.mark.xfail(strict=True, reason="B-T04: negated airport transfer becomes departure")),
    ("Tour Erbil.", "unknown"),
])
def test_source_role_requires_positive_departure_evidence(text, role):
    from services.itinerary.day_facts import source_day_facts
    facts = source_day_facts(RouteDay(1, "", text), "Erbil")
    assert facts["role"] == role


@pytest.mark.parametrize("number", [
    0, -1, None, "1.5",
    pytest.param(1.5, marks=pytest.mark.xfail(strict=True, reason="B-T05: fractional day silently becomes day 1")),
    pytest.param(True, marks=pytest.mark.xfail(strict=True, reason="B-T05: boolean silently becomes day 1")),
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
