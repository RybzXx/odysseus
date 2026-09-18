"""Minimal reproductions from the 2026-09-18 sent-offer audit.

The repaired production paths must satisfy each historical contract.
Fixtures contain synthetic prose and no customer correspondence.
"""
from types import SimpleNamespace

import pytest

from services.itinerary.binder import bind_route_to_templates
from services.itinerary.models import RouteDay, RouteRecord
from services.itinerary.matcher import activity_regions
from services.itinerary.regions import REGION_CENTRAL, REGION_SOUTH, REGION_KURDISTAN


def template(city, overnight, title, text):
    return SimpleNamespace(city=city, overnight_city=overnight, title=title,
                           full_text=text, included_sites=[], active=True,
                           region=REGION_CENTRAL)


def route(city, text):
    return RouteRecord("audit", "synthetic", 1, "individual", [city] if city else [],
                       [], [RouteDay(1, city, text)], {REGION_CENTRAL})


@pytest.mark.parametrize("city", ["Nasiriyah,", "Nasiriyah."])
def test_overnight_punctuation_does_not_remove_a_known_city(city):
    templates = {"NAS_TEST": template("Nasiriyah", "Nasiriyah", "Nasiriyah visit", "Visit Ur.")}
    plain, _ = bind_route_to_templates(route("Nasiriyah", "Visit Ur."), templates, [REGION_SOUTH])
    punctuated, _ = bind_route_to_templates(route(city, "Visit Ur."), templates, [REGION_SOUTH])
    assert plain == ["NAS_TEST"]
    assert punctuated == plain


@pytest.mark.parametrize("text", [
    "Old Baghdad day tour. Return to Baghdad after visiting the markets.",
    "Samarra day tour. Visit Samarra and Fallujah, then return to Baghdad.",
])
def test_no_overnight_does_not_authorize_an_unrelated_airport_departure(text):
    templates = {
        "BG_TEST": template("Baghdad", "Baghdad", "Baghdad visit", text),
        "DEP_TEST": template("Mosul / Erbil", "", "Departure from Erbil", "Drive from Mosul to Erbil airport."),
    }
    codes, gaps = bind_route_to_templates(route("", text), templates, [REGION_CENTRAL])
    # An unresolved route may stop. It must not substitute an unrelated flight.
    assert "DEP_TEST" not in codes
    assert codes or gaps


@pytest.mark.parametrize("alias,region", [
    ("Chibayesh", REGION_SOUTH),
    ("Sulimaniyah", REGION_KURDISTAN),
])
def test_region_matching_recognizes_activity_place_aliases(alias, region):
    days = [RouteDay(1, "", f"Visit {alias}.")]
    assert region in activity_regions(days)


def test_full_binding_preserves_the_requested_overnight_count():
    from services.itinerary.propose_sequence import active_day_templates

    templates = active_day_templates()
    historical = RouteRecord("audit", "synthetic", 2, "individual", ["Basra", "Nasiriyah"], [], [
        RouteDay(1, "Basra", "Visit Basra and stay overnight in Basra."),
        RouteDay(2, "Nasiriyah", "Visit Qurna, the marshes, and Ur. Stay overnight in Nasiriyah."),
    ], {REGION_SOUTH})
    codes, gaps = bind_route_to_templates(historical, templates, [REGION_SOUTH])
    if len(codes) == len(historical.days):
        assert [templates[c].overnight_city for c in codes] == historical.city_sequence
    else:
        assert gaps
