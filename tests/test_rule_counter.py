"""
tests/test_rule_counter.py

Tests for the rule counter: counts taken from the sent offers, with no model.

The point of counting rather than asking a model is that anybody can check the
answer. These tests hold that promise by building small corpora whose right
answer is countable by reading the fixture.

Per tests/TESTING_STANDARD.md: no network, no sheet, no mailbox. Every offer
here is built in the test.
"""
import sys
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.offers.models import OfferDay, SentOffer  # noqa: E402
from services.offers.rule_counter import (  # noqa: E402
    FAMILY_FIRST_NIGHT,
    FAMILY_LAST_NIGHT,
    FAMILY_MOVE,
    FAMILY_TRIP_LENGTH,
    MIN_OBSERVATIONS,
    MIN_SHARE,
    canonical_city,
    count_rules,
    nights_of,
)


def offer(*cities, day_count=None):
    """
    One offer whose nights are `cities`. "" means a day with no overnight.

    The last day of a real offer is a departure and carries no overnight city,
    so a test that wants a departure passes "" last.
    """
    days = [OfferDay(day_number=i + 1, text=f"day {i + 1}", overnight_city=c)
            for i, c in enumerate(cities)]
    return SentOffer(message_id=f"m{id(days)}", subject="s", sent_at=None,
                     days=days)


def many(count, *cities):
    return [offer(*cities) for _ in range(count)]


# ── Naming a city ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, wanted", [
    ("Baghdad", "Baghdad"),
    ("  Baghdad  ", "Baghdad"),
    ("Baghdad (Not Included)", "Baghdad"),
    ("Baghdad  1", "Baghdad"),
    ("Mosul:", "Mosul"),
    ("Nasiriyah,", "Nasiriyah"),
    ("Chibayish.", "Chibayish"),
])
def test_a_city_keeps_its_name_through_punctuation_and_notes(raw, wanted):
    """
    A variant left alone splits one habit into two counts, and both then fall
    under the floor. The corpus held 38 strings for about a dozen places.
    """
    assert canonical_city(raw) == wanted


@pytest.mark.parametrize("raw", [
    "Sulaymaniya", "Sulimaniyah", "Sulaymaniah", "sulaymaniyah",
])
def test_every_spelling_of_sulaymaniyah_counts_as_one_city(raw):
    assert canonical_city(raw) == "Sulaymaniyah"


def test_chibayesh_and_chibayish_are_one_city():
    assert canonical_city("Chibayesh") == canonical_city("Chibayish") == "Chibayish"


@pytest.mark.parametrize("raw", [
    "Duhok or Erbil",
    "Nasiriyah OR homestay in Chibayish",
    "Duhok or Possible Homestay in Amedi area.",
])
def test_a_choice_of_two_places_is_refused(raw):
    """
    Counting "Duhok or Erbil" as either one invents evidence the offer does not
    carry. The night is dropped and reported instead.
    """
    assert canonical_city(raw) == ""


def test_a_sentence_in_the_overnight_cell_is_refused():
    assert canonical_city("Baghdad For the designed itinerary of 4 Days") == ""


@pytest.mark.parametrize("raw", ["", "   ", "123", "-"])
def test_an_empty_or_wordless_cell_names_no_city(raw):
    assert canonical_city(raw) == ""


def test_a_refused_night_shortens_the_trip_and_joins_no_move():
    """
    Dropping a night must not make its neighbours adjacent. That would record a
    move between two cities the trip never took in one step.
    """
    nights = nights_of(offer("Baghdad", "Duhok or Erbil", "Basra"))
    assert nights == ["Baghdad", "Basra"]


# ── The population ───────────────────────────────────────────────────────────

def test_a_trip_with_one_night_is_left_out_of_every_family():
    """
    Its first night is also its last, so counting it would state one fact twice
    under two family names. It has no move either.
    """
    report = count_rules(many(20, "Baghdad", ""))
    assert report.offers_read == 20
    assert report.offers_counted == 0
    assert report.rules == []


def test_the_report_says_how_much_of_the_corpus_stayed_silent():
    corpus = many(12, "Baghdad", "Mosul") + many(5, "Erbil", "")
    report = count_rules(corpus)
    assert report.offers_read == 17
    assert report.offers_counted == 12


def test_a_refused_night_is_counted_and_shown():
    report = count_rules(many(3, "Baghdad", "Duhok or Erbil", "Basra"))
    assert report.nights_refused == 3
    assert report.nights_named == 6
    assert "Duhok or Erbil" in report.refused_examples


def test_one_refused_wording_is_reported_once():
    report = count_rules(many(9, "Baghdad", "Duhok or Erbil", "Basra"))
    assert report.refused_examples.count("Duhok or Erbil") == 1


# ── First and last night ─────────────────────────────────────────────────────

def test_the_first_night_is_counted_against_every_counted_trip():
    report = count_rules(many(12, "Baghdad", "Mosul"))
    rules = report.of_family(FAMILY_FIRST_NIGHT)
    assert len(rules) == 1
    assert rules[0].subject == "Baghdad"
    assert (rules[0].count, rules[0].total) == (12, 12)
    assert rules[0].statement == "12 of 12 trips spend the first night in Baghdad."


def test_the_last_night_is_the_last_named_night_not_the_last_day():
    """A trip ends with a departure day that carries no overnight city."""
    report = count_rules(many(12, "Baghdad", "Erbil", ""))
    rules = report.of_family(FAMILY_LAST_NIGHT)
    assert [r.subject for r in rules] == ["Erbil"]


def test_a_first_night_below_the_observation_floor_states_no_rule():
    corpus = many(MIN_OBSERVATIONS - 1, "Basra", "Mosul") + many(40, "Baghdad", "Mosul")
    subjects = [r.subject for r in count_rules(corpus).of_family(FAMILY_FIRST_NIGHT)]
    assert subjects == ["Baghdad"]


def test_a_first_night_below_the_share_floor_states_no_rule():
    """
    Enough observations, too small a share. Ten of a hundred is a habit of one
    trip in ten, and calling that what trips do would mislead.
    """
    corpus = many(10, "Basra", "Mosul") + many(90, "Baghdad", "Mosul")
    rules = count_rules(corpus).of_family(FAMILY_FIRST_NIGHT)
    assert [r.subject for r in rules] == ["Baghdad"]
    assert 10 / 100 < MIN_SHARE


# ── Moves ────────────────────────────────────────────────────────────────────

def test_a_move_is_counted_against_the_nights_spent_in_the_city_it_leaves():
    """
    The rule answers "given a night here, where next". Its population is the
    transitions out of that city, not every transition in the corpus.
    """
    corpus = many(30, "Baghdad", "Mosul") + many(10, "Basra", "Najaf")
    rules = count_rules(corpus).of_family(FAMILY_MOVE)
    by_subject = {r.subject: r for r in rules}
    assert by_subject["Baghdad -> Mosul"].total == 30
    assert by_subject["Basra -> Najaf"].total == 10


def test_a_second_night_in_one_city_is_a_move_to_itself():
    """
    Trips linger. "After a night in Baghdad the next night is in Baghdad again"
    is the commonest single fact in the corpus, and dropping it would leave the
    planner thinking every night changes city.
    """
    report = count_rules(many(20, "Baghdad", "Baghdad", "Mosul"))
    rules = {r.subject: r for r in report.of_family(FAMILY_MOVE)}
    stay = rules["Baghdad -> Baghdad"]
    assert (stay.count, stay.total) == (20, 40)
    assert "again" in stay.statement


def test_a_move_rule_carries_the_two_cities_apart_from_its_label():
    report = count_rules(many(15, "Baghdad", "Mosul"))
    rule = report.of_family(FAMILY_MOVE)[0]
    assert (rule.from_city, rule.to_city) == ("Baghdad", "Mosul")


def test_a_departure_day_ends_the_trip_and_starts_no_move():
    report = count_rules(many(15, "Baghdad", "Mosul", ""))
    assert [r.subject for r in report.of_family(FAMILY_MOVE)] == ["Baghdad -> Mosul"]


# ── Trip length ──────────────────────────────────────────────────────────────

def test_trip_length_counts_days_and_not_nights():
    """A 3-day trip has two nights and a departure. Its length is 3."""
    report = count_rules(many(12, "Baghdad", "Mosul", ""))
    rules = report.of_family(FAMILY_TRIP_LENGTH)
    assert [r.subject for r in rules] == ["3"]


def test_trip_length_reports_the_spread_and_not_only_the_winner():
    """
    A share floor asks whether one outcome dominates. With 15 possible lengths
    the mass spreads and no length can dominate, so the observation floor alone
    decides. At a 15 percent floor this family produced one rule over the live
    corpus and hid the shape of the demand.
    """
    corpus = (many(12, *(["Baghdad"] * 3)) + many(12, *(["Baghdad"] * 5))
              + many(12, *(["Baghdad"] * 8)) + many(12, *(["Baghdad"] * 11)))
    rules = count_rules(corpus).of_family(FAMILY_TRIP_LENGTH)
    assert sorted(int(r.subject) for r in rules) == [3, 5, 8, 11]
    assert all(r.share < MIN_SHARE + 0.11 for r in rules)


# ── The promise ──────────────────────────────────────────────────────────────

def test_every_statement_carries_its_own_count_and_population():
    """
    A statement a reader cannot check is exactly what counting avoids. Both
    numbers appear in the sentence, so the sentence stands alone.
    """
    corpus = many(20, "Baghdad", "Baghdad", "Mosul", "")
    for rule in count_rules(corpus).rules:
        assert str(rule.count) in rule.statement, rule.statement
        assert str(rule.total) in rule.statement, rule.statement
        assert rule.count <= rule.total
        assert 0 < rule.share <= 1


def test_a_rule_key_is_stable_across_two_runs_of_one_corpus():
    """A record tracks a rule by this key, so it must not move between runs."""
    corpus = many(20, "Baghdad", "Mosul", "")
    first = {r.rule_key for r in count_rules(corpus).rules}
    second = {r.rule_key for r in count_rules(corpus).rules}
    assert first == second
    assert "first_night:Baghdad" in first
    assert "move:Baghdad -> Mosul" in first


def test_an_empty_corpus_states_no_rule_and_does_not_fail():
    report = count_rules([])
    assert report.rules == []
    assert report.offers_read == 0
