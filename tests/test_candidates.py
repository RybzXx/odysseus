"""
tests/test_candidates.py

Several itineraries for one request, all built by the rules.

Two defects these guard against. A candidate set built by score alone puts a
one-day itinerary in front of a four-day one, because `score_route` weights
region at 0.50 against day count at 0.35, so a route half the asked length ties
whenever the regions match. A ranker that saw faults and no shortfall would
then choose it: a one-day itinerary repeats nothing, so it has no faults.

Measured on 2026-09-07 over the four live queue drafts: 7, 7, 14 and 20 routes
tie, and the binder delivers 1 to 7 days against 4 and 10 asked.

Per tests/TESTING_STANDARD.md: no network, no mail, and no model.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary.candidates import (  # noqa: E402
    CANDIDATE_CEILING,
    Candidate,
    build_candidates,
    candidate_set_to_dict,
    check_candidates,
    tied_routes,
)
from services.itinerary.models import NormalizedRequest, RouteDay, RouteRecord  # noqa: E402


def a_template(code: str, city: str = "Baghdad", title: str = "", sites: str = "[]"):
    """
    One day template in the shape the binder reads.

    `_index_templates` uses `getattr`, so a dict answers the default for every
    field and binds to nothing. `active_day_templates()` returns objects, which
    is why production works and a dict fixture does not.
    """
    return SimpleNamespace(code=code, overnight_city=city, city=city,
                           title=title or f"{city} day", active=True,
                           included_sites_json=sites, region="Central Iraq")


BAGHDAD_TEMPLATES = {"BG1CT": a_template("BG1CT")}


def a_request(day_count: int = 4, regions=("Central Iraq",)) -> NormalizedRequest:
    return NormalizedRequest(
        key="queue:qr-test", source="queue", customer_name="A Customer",
        pax=2, day_count=day_count, tour_type="individual", hotel_tier="3star",
        vehicle_type="SMALL_CAR", requested_regions=list(regions))


def a_route(name: str, days: int, cities, regions=("Central Iraq",)) -> RouteRecord:
    return RouteRecord(
        id=name, source_file=name, day_count=days, tour_type="individual",
        city_sequence=list(cities), themes=[],
        days=[RouteDay(day=i + 1, overnight_city=c, text=f"Day {i + 1} in {c}")
              for i, c in enumerate(cities)],
        region_set=set(regions))


# ── the tie ──────────────────────────────────────────────────────────────────

def test_an_empty_corpus_gives_nothing():
    routes, top = tied_routes(a_request(), routes=[])
    assert routes == []
    assert top == 0.0


def test_the_tie_orders_by_length_before_score():
    """
    The candidate a customer could be sold comes first.

    Both routes tie on region. The four-day route answers a four-day request
    and the one-day route does not, and only the length ordering says so.
    """
    short = a_route("one-day.docx", 1, ["Baghdad"])
    right = a_route("four-day.docx", 4, ["Baghdad", "Karbala", "Najaf", "Baghdad"])
    routes, _ = tied_routes(a_request(day_count=4), routes=[short, right])

    assert [r.source_file for r in routes][0] == "four-day.docx"


def test_a_route_of_a_different_region_does_not_tie():
    central = a_route("central.docx", 4, ["Baghdad"], regions=("Central Iraq",))
    north = a_route("north.docx", 4, ["Erbil"], regions=("Northern Iraq",))
    routes, _ = tied_routes(a_request(regions=("Central Iraq",)),
                            routes=[central, north])

    assert [r.source_file for r in routes] == ["central.docx"]


def test_the_tie_is_read_and_find_best_route_is_untouched():
    """Spec item 19.7. The scorer keeps its own answer."""
    from services.itinerary.matcher import find_best_route

    corpus = [a_route("a.docx", 4, ["Baghdad"]), a_route("b.docx", 4, ["Karbala"])]
    best, _ = find_best_route(a_request(), routes=corpus)
    routes, _ = tied_routes(a_request(), routes=corpus)

    assert best in routes


# ── the candidates ───────────────────────────────────────────────────────────

def test_a_request_with_no_matching_route_says_so():
    found = build_candidates(a_request(), {}, routes=[])
    assert found.is_empty is True
    assert "corpus is empty" in found.untested[0]


def test_a_route_that_binds_to_no_day_is_not_a_candidate():
    """An empty candidate would reach a ranker as a choice with no itinerary."""
    found = build_candidates(a_request(), {}, routes=[a_route("x.docx", 4, ["Atlantis"])])
    assert found.is_empty is True
    assert "bound to no day" in found.untested[0]


def test_the_ceiling_caps_the_candidates_and_the_record_says_so():
    corpus = [a_route(f"r{i}.docx", 4, ["Baghdad"]) for i in range(12)]
    templates = BAGHDAD_TEMPLATES
    found = build_candidates(a_request(), templates, routes=corpus)

    assert len(found.candidates) <= CANDIDATE_CEILING
    assert found.tied_routes == 12
    assert any("ceiling" in note for note in found.untested)


def test_every_candidate_is_numbered_from_one():
    templates = BAGHDAD_TEMPLATES
    corpus = [a_route(f"r{i}.docx", 4, ["Baghdad"]) for i in range(3)]
    found = build_candidates(a_request(), templates, routes=corpus)

    assert [c.index for c in found.candidates] == list(
        range(1, len(found.candidates) + 1))


# ── the shortfall ────────────────────────────────────────────────────────────

def test_a_candidate_names_how_many_days_it_is_short():
    candidate = Candidate(index=1, route_id="x", route_name="x.docx",
                          route_days=4, match_score=0.8, region_coverage=1.0,
                          asked_days=4, day_codes=["ARRBG"])
    assert candidate.day_shortfall == 3
    assert "3 day(s) short" in candidate.statement


def test_a_candidate_that_answers_the_length_is_not_short():
    candidate = Candidate(index=1, route_id="x", route_name="x.docx",
                          route_days=4, match_score=0.8, region_coverage=1.0,
                          asked_days=4, day_codes=["A", "B", "C", "D"])
    assert candidate.day_shortfall == 0
    assert "short" not in candidate.statement


def test_a_request_with_no_day_count_reports_no_shortfall():
    candidate = Candidate(index=1, route_id="x", route_name="x.docx",
                          route_days=4, match_score=0.8, region_coverage=1.0,
                          asked_days=0, day_codes=["A"])
    assert candidate.day_shortfall == 0


def test_a_candidate_delivering_more_days_than_asked_is_not_short():
    candidate = Candidate(index=1, route_id="x", route_name="x.docx",
                          route_days=6, match_score=0.8, region_coverage=1.0,
                          asked_days=4, day_codes=["A", "B", "C", "D", "E"])
    assert candidate.day_shortfall == 0


# ── the spread, and the wire shape ───────────────────────────────────────────

def test_an_empty_set_has_no_spread():
    from services.itinerary.candidates import CandidateSet

    assert CandidateSet().spread["differ"] is False


def test_candidates_of_different_lengths_differ():
    from services.itinerary.candidates import CandidateSet

    found = CandidateSet(candidates=[
        Candidate(index=1, route_id="a", route_name="a", route_days=4,
                  match_score=0.8, region_coverage=1.0, asked_days=4,
                  day_codes=["A", "B"]),
        Candidate(index=2, route_id="b", route_name="b", route_days=4,
                  match_score=0.8, region_coverage=1.0, asked_days=4,
                  day_codes=["A"]),
    ])
    assert found.spread["days"] == [2, 1]
    assert found.spread["differ"] is True


def test_the_wire_shape_carries_the_shortfall_and_the_check():
    templates = BAGHDAD_TEMPLATES
    found = build_candidates(a_request(), templates,
                             routes=[a_route("r.docx", 4, ["Baghdad"])])
    check_candidates(found, templates, request_row={}, day_count=4)
    wire = candidate_set_to_dict(found)

    assert wire["ceiling"] == CANDIDATE_CEILING
    assert wire["candidates"][0]["day_shortfall"] >= 0
    assert wire["candidates"][0]["check"] is not None


def test_a_candidate_with_faults_is_still_a_candidate():
    """
    Layer 3 never refuses and the human is the gate (ws-03 D41, D15). A set
    that dropped a faulty candidate would decide instead of report.
    """
    templates = BAGHDAD_TEMPLATES
    found = build_candidates(a_request(), templates,
                             routes=[a_route("r.docx", 4, ["Baghdad", "Baghdad"])])
    before = len(found.candidates)
    check_candidates(found, templates, request_row={}, day_count=4)

    assert len(found.candidates) == before
