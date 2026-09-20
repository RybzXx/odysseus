"""Customer arrival notes must constrain the route without a network model."""
from datetime import date
from types import SimpleNamespace

import pytest

from services.itinerary.normalizer import normalize_queue_record
from services.itinerary.resolved_plan import resolve_plan, stale_plan_errors
from services.itinerary.sequence_check import check_sequence


def normalize(notes, **fields):
    return normalize_queue_record("queue:test", {
        "trip_days": "1", "travel_date": "2026-11-09", "entry_notes": notes, **fields})


def templates():
    return {city: SimpleNamespace(code=city, title=f"{city} city tour", city=city,
        overnight_city=city, region="Southern Iraq", full_text=f"Visit {city}.",
        included_sites=[], pricing_tags=[], active=True, needs_review=False)
        for city in ("Basra", "Baghdad")}


@pytest.mark.parametrize("notes,city", [
    ("Arriving in Basra on Nov 9th, visiting Ur, Eridu, Nippur, Borsippa, "
     "Najaf, Kerbala, and being in Baghdad on Nov 13th.", "Basra"),
    ("We will arrive in Basra on November 9th.", "Basra"),
    ("Arrival at Basra International Airport at 10:30", "Basra"),
    ("Landing in Basrah on May 9th", "Basra"),
    ("Arrive in Nasiriya", "Nasiriyah"),
    ("Arriving in Basra. Arriving in Basrah.", "Basra"),
])
def test_explicit_arrival_is_preserved_with_provenance(notes, city):
    req = normalize(notes)
    assert req.arrival_city == city
    assert req.requirement_sources["arrival_city"] == "explicit arrival statement in entry_notes"
    assert not req.parse_warnings
    assert req.raw_record["entry_notes"] == notes
    assert "Entry notes: " + notes in req.special_notes
    assert not req.departure_city
    assert not req.required_cities


@pytest.mark.parametrize("notes", [
    "We are not arriving in Basra.", "We may arrive in Basra.",
    "Arriving in Basra is optional.", "Arriving in Basra or Baghdad.",
    "Arriving in Basra. Arriving in Baghdad.",
    "Previous itinerary: arriving in Basra.",
    "Arriving in Basra?", 'Example: "Arriving in Basra"',
    "Arriving in Atlantis.", "Arrival city is not known.",
    "Arriving in Basra then Baghdad.",
])
def test_unresolved_arrival_requires_review(notes):
    req = normalize(notes)
    assert not req.arrival_city
    assert any("Confirm the arrival city" in warning for warning in req.parse_warnings)
    checked = check_sequence(["Basra"], templates(), normalized_request=req)
    assert not checked.is_clean
    assert set(req.parse_warnings) <= set(checked.untested)


@pytest.mark.parametrize("notes", ["Visit Basra and Baghdad", "Departure from Basra",
    "Travel by land from Basra to Baghdad", "", None])
def test_other_mentions_supply_no_arrival(notes):
    req = normalize(notes)
    assert not req.arrival_city
    assert not req.parse_warnings


def test_model_notes_supply_no_arrival():
    req = normalize("Visit Ur", special_notes="Arriving in Basra", summary="Arriving in Basra")
    assert not req.arrival_city


def test_structured_field_conflict_blocks_without_overwriting_it():
    req = normalize("Arriving in Basra", arrival_city="Baghdad")
    assert req.arrival_city == "Baghdad"
    assert req.requirement_sources["arrival_city"] == "explicit request field"
    assert any("Arrival city conflict" in warning for warning in req.parse_warnings)


def test_matching_field_and_notes_need_no_review():
    req = normalize("Arriving in Basrah", arrival_city="Basra")
    assert req.arrival_city == "Basra"
    assert not req.parse_warnings


def test_notes_reject_baghdad_start_and_invalidate_old_saved_plan():
    rows = templates()
    req = normalize("Arriving in Basra on Nov 9th, visiting Ur, then Baghdad.")
    req.start_date = date(2026, 11, 9)
    checked = check_sequence(["Baghdad"], rows, normalized_request=req)
    assert [f.statement for f in checked.of_kind("required_endpoint")] == ["The arrival city must be Basra."]
    assert not check_sequence(["Basra"], rows, normalized_request=req).of_kind("required_endpoint")
    legacy = normalize(req.raw_record["entry_notes"])
    legacy.arrival_city = ""
    legacy.requirement_sources = {}
    stored = resolve_plan(["Baghdad"], rows, legacy).to_dict()
    assert stale_plan_errors(stored, req, rows, ["Baghdad"])


def test_basra_candidate_is_visible_before_wrong_start_even_when_incomplete():
    from services.itinerary.candidates import build_candidates
    from services.itinerary.models import RouteDay, RouteRecord
    rows = templates()
    rows["BG2"] = SimpleNamespace(**{**vars(rows["Baghdad"]), "code": "BG2"})
    req = normalize("Arriving in Basra", trip_days="2")
    req.requested_regions = []
    routes = [RouteRecord(id=city, source_file=city, day_count=count,
        tour_type="individual", city_sequence=[city] * count, themes=[],
        days=[RouteDay(day=i + 1, overnight_city=city, text=f"Visit {city}. Overnight in {city}.")
              for i in range(count)]) for city, count in (("Baghdad", 2), ("Basra", 1))]
    found = build_candidates(req, rows, routes=routes, ceiling=1)
    best = found.candidates[0]
    assert best.plan.days[0]["start_city"] == "Basra"
    assert not best.check.of_kind("required_endpoint")
    assert best.check.of_kind("day_count")
    assert not best.check.is_clean
