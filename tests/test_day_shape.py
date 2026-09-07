"""
tests/test_day_shape.py

Tests for the shape of a template's day: its start, its end and its role.

The defect these guard against is a shape that reads confidently and is wrong.
A wrong start hides a template that fits, and the binder reports nothing when it
does. That is worse than the word overlap it replaces, because a low overlap at
least produced an answer.

The owner read 21 templates and gave a start, an end and a role for each. Those
values must never be derived over, and a reader of a wrong filter must be able
to see who to ask.

Per tests/TESTING_STANDARD.md: no network, no mail, and no model.
"""
import sys
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary import day_shape  # noqa: E402
from services.itinerary.day_shape import (  # noqa: E402
    OWNER_SETTLED_SHAPES,
    ROLE_ARRIVAL,
    ROLE_CITY_DAY,
    ROLE_DAY_TRIP,
    ROLE_DEPARTURE,
    ROLE_FROM_TITLE,
    ROLE_TRANSIT,
    ROLES,
    SOURCE_CATALOGUE,
    SOURCE_OWNER,
    SOURCE_TITLE,
    all_shapes,
    shape_of,
    shapes_without_a_start,
    summary,
)


def row(city="", overnight="", title=""):
    return {"city": city, "overnight_city": overnight, "title": title,
            "included_sites": []}


@pytest.fixture(autouse=True)
def clear_cache():
    before = day_shape._SHAPES
    day_shape._SHAPES = None
    yield
    day_shape._SHAPES = before


# ── the owner's answers always win ───────────────────────────────────────────

def test_the_owner_beats_the_catalogue():
    """
    `SAFA` reads "Samarra / Baghdad area" and sleeps in Baghdad. The catalogue
    would call it a transit out of Samarra. The owner says it is a Baghdad day
    trip, and that is why this table exists.
    """
    shape = shape_of("SAFA", row(city="Samarra / Baghdad area", overnight="Baghdad"))
    assert shape.role == ROLE_DAY_TRIP
    assert shape.start_city == "Baghdad"
    assert shape.end_city == "Baghdad"
    assert shape.source == SOURCE_OWNER


def test_the_owner_beats_a_title_that_says_otherwise():
    shape = shape_of("MOBKHEB", row(city="Bakhdida / Erbil", overnight="",
                                    title="Bakhdida & Drive to Erbil (Departure Day)"))
    assert shape.source == SOURCE_OWNER
    assert (shape.start_city, shape.end_city) == ("Mosul", "Erbil")


def test_a_day_tour_carries_no_fixed_start():
    """
    Babylon sits 44 km from Karbala and 99 km from Baghdad. A trip reaches it
    from either, so pinning `BB` to one would hide it from the other.
    """
    shape = shape_of("BB", row(city="Babylon", overnight=""))
    assert shape.role == ROLE_DAY_TRIP
    assert shape.start_city is None
    assert shape.has_fixed_start is False


def test_every_settled_shape_names_a_known_role():
    for code, (_, _, role) in OWNER_SETTLED_SHAPES.items():
        assert role in ROLES, code


def test_the_owner_settled_twenty_one():
    assert len(OWNER_SETTLED_SHAPES) == 21


# ── a title states what a chain of one city cannot ───────────────────────────

def test_a_title_that_says_arrival_gives_an_arrival():
    shape = shape_of("ARRBG", row(city="Baghdad", overnight="Baghdad",
                                  title="Arrival & Baghdad Landmarks"))
    assert shape.role == ROLE_ARRIVAL
    assert shape.source == SOURCE_TITLE
    assert shape.start_city == "Baghdad"


def test_a_departure_ends_where_the_chain_ends_and_not_where_it_sleeps():
    """`SUEBDEP` sleeps nowhere and flies out of Erbil."""
    shape = shape_of("SUEBDEP", row(city="Sulaymaniyah / Erbil", overnight="",
                                    title="Sulaymaniyah Bazaar & Departure from Erbil"))
    assert shape.role == ROLE_DEPARTURE
    assert shape.start_city == "Sulaymaniyah"
    assert shape.end_city == "Erbil"


def test_a_title_that_says_a_drive_gives_a_role_and_no_start():
    """
    `ArrSU` reads "Drive to Sulaymaniyah". Its chain names one city, so the
    catalogue would call it a city day. Nobody has said where it drives from.
    """
    shape = shape_of("ArrSU", row(city="Sulaymaniyah", overnight="Sulaymaniyah",
                                  title="Drive to Sulaymaniyah & Amna Suraka"))
    assert shape.role == ROLE_TRANSIT
    assert shape.start_city is None
    assert shape.source == SOURCE_TITLE


def test_both_title_only_codes_are_named():
    assert set(ROLE_FROM_TITLE) == {"ArrSU", "NA1"}


# ── what the catalogue alone can say ─────────────────────────────────────────

def test_one_city_and_a_night_there_is_a_city_day():
    shape = shape_of("BG1", row(city="Baghdad", overnight="Baghdad",
                                title="Old Baghdad Alone"))
    assert shape.role == ROLE_CITY_DAY
    assert (shape.start_city, shape.end_city) == ("Baghdad", "Baghdad")
    assert shape.source == SOURCE_CATALOGUE


def test_more_than_one_city_and_a_night_at_the_first_is_a_day_trip():
    shape = shape_of("ZuBA", row(city="Basra / Zubair", overnight="Basra",
                                 title="Zubair & Free Day in Basra"))
    assert shape.role == ROLE_DAY_TRIP
    assert (shape.start_city, shape.end_city) == ("Basra", "Basra")


def test_a_night_somewhere_other_than_the_first_city_is_a_transit():
    shape = shape_of("MOQOLA", row(city="Nineveh Governorate / Duhok",
                                   overnight="Duhok",
                                   title="Plains of Nineveh, Alqosh & Lalish"))
    assert shape.role == ROLE_TRANSIT
    assert (shape.start_city, shape.end_city) == ("Mosul", "Duhok")


def test_a_place_the_map_cannot_hold_is_left_out_of_the_chain():
    """"Nineveh" resolves to Mosul. A name with no place would shift the start."""
    shape = shape_of("X", row(city="Atlantis / Erbil", overnight="Erbil"))
    assert shape.start_city == "Erbil"
    assert shape.role == ROLE_CITY_DAY


def test_an_empty_template_raises_nothing():
    shape = shape_of("X", row())
    assert shape.role == ROLE_DEPARTURE
    assert shape.start_city is None
    assert shape.end_city is None


# ── the whole catalogue ──────────────────────────────────────────────────────

def test_every_template_gets_a_shape():
    from services.itinerary.generator import load_templates

    templates = load_templates()
    shapes = all_shapes(templates)
    assert set(shapes) == set(templates)
    for code, shape in shapes.items():
        assert shape.role in ROLES, code
        assert shape.source in (SOURCE_OWNER, SOURCE_TITLE, SOURCE_CATALOGUE), code


def test_only_three_templates_carry_no_start():
    from services.itinerary.generator import load_templates

    without = dict(shapes_without_a_start(load_templates()))
    assert set(without) == {"BB", "ArrSU", "NA1"}


def test_the_summary_counts_every_template_one_time():
    from services.itinerary.generator import load_templates

    templates = load_templates()
    found = summary(templates)
    assert found["count"] == len(templates)
    assert sum(found["by_source"].values()) == len(templates)
    assert sum(found["by_role"].values()) == len(templates)
    assert found["by_source"][SOURCE_OWNER] == len(OWNER_SETTLED_SHAPES)
