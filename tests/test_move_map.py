"""
tests/test_move_map.py

Tests for the map: where places are, and which pairs the work joins.

The defect these guard against is a map that answers confidently about a place
it does not hold. A distance for a misspelled city, a move count of zero for a
pair the corpus carries 19 times, and a route through a city that does not
exist all read as facts to the caller, because nothing in the answer says the
name was not understood.

Per tests/TESTING_STANDARD.md: no network, no mail, and no model. The counted
corpus is injected, so no test here depends on `data/offer_corpus`.
"""
import sys
from collections import Counter
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary import move_map  # noqa: E402
from services.itinerary.move_map import (  # noqa: E402
    DAY_CEILING_KM,
    PLACE_COORDINATES,
    Leg,
    cities_on_the_way,
    leg,
    move_count,
    path_between,
    place_key,
    resolve_place,
    road_km,
)

# A small corpus, so a count is what this file says it is and not what the
# stored offers happen to hold today.
CORPUS = Counter({
    ("Mosul", "Erbil"): 53,
    ("Mosul", "Duhok"): 61,
    ("Erbil", "Sulaymaniyah"): 4,
    ("Sulaymaniyah", "Erbil"): 19,
    ("Baghdad", "Mosul"): 171,
    ("Chibayish", "Basra"): 4,
})


@pytest.fixture(autouse=True)
def injected_corpus():
    """Every test in this file counts against CORPUS, and leaves no cache behind."""
    before = move_map._COUNTED_MOVES
    move_map._COUNTED_MOVES = CORPUS
    yield
    move_map._COUNTED_MOVES = before


# ── resolve_place: one name, however a source spells it ──────────────────────

def test_a_name_the_map_holds_comes_back_unchanged():
    assert resolve_place("Baghdad") == "Baghdad"


def test_the_ticket_index_spelling_resolves_to_the_map_spelling():
    assert resolve_place("Suli") == "Sulaymaniyah"
    assert resolve_place("Baashiqa") == "Bashiqa"
    assert resolve_place("Chibayesh") == "Chibayish"
    assert resolve_place("Qosh") == "Alqosh"


def test_case_alone_does_not_make_a_new_place():
    assert resolve_place("BAGHDAD") == "Baghdad"
    assert resolve_place("  mosul  ") == "Mosul"


def test_a_place_the_map_does_not_hold_gives_an_empty_name():
    assert resolve_place("Atlantis") == ""
    assert resolve_place("") == ""
    assert resolve_place(None) == ""


def test_the_spelling_the_sold_routes_use_resolves():
    """`Sulimaniyah` sits on 5 route days and was in none of the alias lists."""
    assert resolve_place("Sulimaniyah") == "Sulaymaniyah"


# ── place_key: the one name a place is stored and read under ────────────────

def test_a_place_the_map_holds_is_keyed_by_the_map_spelling():
    assert place_key("Suli") == "Sulaymaniyah"
    assert place_key("Sulimaniyah") == "Sulaymaniyah"


def test_a_place_the_map_lacks_keeps_its_own_name():
    """Rezan carries 14 nights and no coordinate. It must not collapse to ""."""
    assert place_key("Rezan") == "Rezan"
    assert place_key("  Serzan  ") == "Serzan"


def test_an_empty_name_keys_to_nothing():
    assert place_key("") == ""
    assert place_key(None) == ""


# ── road_km: a number, or nothing ────────────────────────────────────────────

def test_a_city_to_itself_is_no_distance():
    assert road_km("Baghdad", "Baghdad") == 0.0


def test_two_spellings_of_one_city_are_no_distance_apart():
    assert road_km("Suli", "Sulaymaniyah") == 0.0


def test_distance_is_the_same_in_both_directions():
    assert road_km("Baghdad", "Mosul") == pytest.approx(road_km("Mosul", "Baghdad"))


def test_the_model_agrees_with_the_measured_baghdad_to_mosul_road():
    # 410 km measured. The module states its error as about 20 percent.
    assert road_km("Baghdad", "Mosul") == pytest.approx(410, rel=0.2)


def test_an_unknown_place_gives_no_distance_rather_than_a_guess():
    assert road_km("Atlantis", "Baghdad") is None
    assert road_km("Baghdad", "Atlantis") is None
    assert road_km("", "") is None
    assert road_km(None, None) is None


# ── Leg: what the corpus says and what distance says, kept apart ─────────────

def test_a_leg_the_corpus_carries_reads_as_joined():
    assert leg("Mosul", "Erbil").is_joined is True


def test_a_leg_the_corpus_never_carries_reads_as_not_joined():
    assert leg("Mosul", "Sulaymaniyah").is_joined is False
    assert leg("Sulaymaniyah", "Mosul").is_joined is False


def test_a_pair_carried_one_way_is_joined_the_other_way():
    """The corpus drives Mosul to Duhok. Duhok to Mosul is the same road."""
    assert move_count("Duhok", "Mosul") == 0
    assert leg("Duhok", "Mosul").is_joined is True
    assert leg("Duhok", "Mosul").joined_direction == "in reverse only"


def test_a_leg_keeps_its_own_direction_count():
    """`is_joined` reads both ways. `count` never stops meaning one way."""
    forward, backward = leg("Mosul", "Duhok"), leg("Duhok", "Mosul")
    assert forward.count == 61 and forward.reverse_count == 0
    assert backward.count == 0 and backward.reverse_count == 61
    assert forward.joined_direction == "as proposed"


def test_a_pair_carried_neither_way_names_no_direction():
    assert leg("Mosul", "Sulaymaniyah").joined_direction == ""


def test_a_leg_under_the_ceiling_is_not_too_long():
    assert leg("Mosul", "Erbil").is_over_ceiling is False


def test_a_leg_over_the_ceiling_is_too_long():
    assert leg("Basra", "Duhok").is_over_ceiling is True
    assert road_km("Basra", "Duhok") > DAY_CEILING_KM


def test_a_leg_with_no_distance_is_never_called_too_long():
    unmeasured = Leg(from_city="Atlantis", to_city="Baghdad", km=None, count=0)
    assert unmeasured.is_over_ceiling is False
    assert unmeasured.hours is None


def test_an_unknown_pair_is_counted_zero_and_not_an_error():
    assert move_count("Basra", "Duhok") == 0


# ── the seam between the map's spelling and the corpus's ────────────────────

def test_a_leg_named_the_ticket_index_way_keeps_its_corpus_count():
    """
    A caller holding a city from the ticket index gets a distance, because
    `road_km` resolves the name. It must get the count too, or the answer says
    the work has never carried a move it carries 19 times, while proving by the
    distance that the place was understood.
    """
    assert leg("Suli", "Erbil").count == leg("Sulaymaniyah", "Erbil").count


def test_a_leg_named_the_ticket_index_way_reads_as_joined():
    assert leg("Chibayesh", "Basra").is_joined is True


# ── path_between: what belongs in the middle ─────────────────────────────────

def test_a_pair_the_corpus_joins_needs_nothing_in_the_middle():
    assert path_between("Mosul", "Erbil") == ["Mosul", "Erbil"]


def test_a_pair_the_corpus_never_joins_names_the_city_between_them():
    assert path_between("Mosul", "Sulaymaniyah") == ["Mosul", "Erbil", "Sulaymaniyah"]


def test_a_city_to_itself_is_a_path_of_one():
    assert path_between("Erbil", "Erbil") == ["Erbil"]


def test_a_pair_nothing_reaches_gives_no_path():
    assert path_between("Basra", "Duhok") == []


def test_no_path_is_offered_through_a_place_the_map_does_not_hold():
    assert path_between("Atlantis", "Atlantis") == []


def test_a_path_is_found_when_the_ends_are_spelled_another_way():
    assert path_between("Suli", "Erbil") == ["Sulaymaniyah", "Erbil"]


# ── cities_on_the_way: what a day passes ─────────────────────────────────────

def test_a_city_on_the_road_is_found():
    found = dict(cities_on_the_way("Baghdad", "Mosul"))
    assert "Samarra" in found
    assert "Hatra" in found


def test_a_city_far_off_the_road_is_not_found():
    assert "Basra" not in dict(cities_on_the_way("Baghdad", "Mosul"))


def test_the_caller_can_refuse_a_place_the_work_does_not_stop_at():
    """Kirkuk lies between Baghdad and Erbil, and no template visits it."""
    everything = dict(cities_on_the_way("Baghdad", "Erbil"))
    allowed = dict(cities_on_the_way("Baghdad", "Erbil", among={"Samarra"}))
    assert "Samarra" in allowed
    assert set(allowed) == {"Samarra"}
    assert set(allowed) <= set(everything)


def test_a_via_city_is_found_even_though_it_never_carries_a_night():
    """Samarra is in no counted move; a test against the counts would lose it."""
    assert move_count("Baghdad", "Samarra") == 0
    assert "Samarra" in dict(cities_on_the_way("Baghdad", "Mosul"))


def test_an_empty_allowed_set_finds_nothing():
    assert cities_on_the_way("Baghdad", "Mosul", among=set()) == []


def test_a_city_to_itself_has_nothing_on_the_way():
    assert cities_on_the_way("Erbil", "Erbil") == []


def test_an_unknown_end_has_nothing_on_the_way():
    assert cities_on_the_way("Atlantis", "Mosul") == []


def test_the_nearest_detour_comes_first():
    found = cities_on_the_way("Baghdad", "Mosul")
    added = [extra for _, extra in found]
    assert added == sorted(added)


# ── the table itself ─────────────────────────────────────────────────────────

def test_every_place_carries_a_pair_of_plausible_iraqi_coordinates():
    for place, (latitude, longitude) in PLACE_COORDINATES.items():
        assert 29 < latitude < 38, place
        assert 38 < longitude < 49, place


def test_no_two_places_share_one_position():
    seen = {}
    for place, position in PLACE_COORDINATES.items():
        assert position not in seen, f"{place} sits on {seen.get(position)}"
        seen[position] = place
