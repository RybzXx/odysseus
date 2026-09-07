"""
tests/test_named_pair_rules.py

Tests for a rule that names two template codes.

Two defects these guard against. A rule read from `requested_regions` can never
fire, because normalisation folds Western Iraq into Northern Iraq on purpose and
the two halves of the condition become one value. A rule that refuses would
reject a sequence the owner said to penalise, and `SAFA` with `SAMO` is a worse
answer rather than a wrong one.

Per tests/TESTING_STANDARD.md: no network, no mail, and no model.
"""
import sys
from pathlib import Path

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary.named_pair_rules import (  # noqa: E402
    EFFECT_ALLOW,
    EFFECT_PENALTY,
    MIN_DAYS_TO_LIFT,
    SAFA_RULE_ID,
    judged_rule_record,
    names_west_and_north,
    safa_verdict,
    verdict_for_fault,
)

WEST_AND_NORTH = {"regions": ["Western Iraq & Nineveh Plains", "Iraqi Kurdistan"]}
CENTRAL_ONLY = {"regions": ["Central Iraq & Middle Euphrates"]}
BOTH_CODES = ["ARRBG", "SAMO", "MO1", "BG3", "SAFA"]


# ── the condition reads the raw text, never the normalised regions ───────────

def test_the_raw_customer_text_names_the_west_and_the_north():
    assert names_west_and_north(WEST_AND_NORTH) is True


def test_the_normalised_regions_could_never_satisfy_the_condition():
    """
    `REGION_NAME_MAP` maps "western iraq" and "nineveh plains" both to
    "Northern Iraq". A condition read from the normalised list sees one value
    where the customer wrote two, so it could never be true.
    """
    from services.itinerary.normalizer import REGION_NAME_MAP

    assert REGION_NAME_MAP["western iraq"] == "Northern Iraq"
    assert REGION_NAME_MAP["western iraq & nineveh plains"] == "Northern Iraq"
    assert names_west_and_north({"regions": ["Northern Iraq"]}) is False


def test_the_north_alone_does_not_satisfy_the_condition():
    assert names_west_and_north({"regions": ["Iraqi Kurdistan"]}) is False


def test_central_iraq_alone_does_not_satisfy_the_condition():
    assert names_west_and_north(CENTRAL_ONLY) is False


def test_a_region_written_as_one_string_is_read_the_same_way():
    assert names_west_and_north(
        {"regions": "Western Iraq & Nineveh Plains, Kurdistan"}) is True


def test_a_record_with_no_region_key_satisfies_nothing():
    assert names_west_and_north({}) is False
    assert names_west_and_north(None) is False


# ── the verdict ──────────────────────────────────────────────────────────────

def test_a_sequence_without_both_codes_gets_no_verdict():
    assert safa_verdict(["ARRBG", "SAMO"], WEST_AND_NORTH, 12) is None
    assert safa_verdict(["ARRBG", "SAFA"], WEST_AND_NORTH, 12) is None
    assert safa_verdict([], WEST_AND_NORTH, 12) is None


def test_both_codes_on_a_short_trip_is_a_penalty():
    verdict = safa_verdict(BOTH_CODES, WEST_AND_NORTH, MIN_DAYS_TO_LIFT - 1)
    assert verdict.effect == EFFECT_PENALTY
    assert verdict.lowers_the_score is True


def test_both_codes_on_a_long_west_and_north_trip_costs_nothing():
    verdict = safa_verdict(BOTH_CODES, WEST_AND_NORTH, MIN_DAYS_TO_LIFT)
    assert verdict.effect == EFFECT_ALLOW
    assert verdict.lowers_the_score is False


def test_a_long_trip_that_names_neither_region_is_still_a_penalty():
    verdict = safa_verdict(BOTH_CODES, CENTRAL_ONLY, 12)
    assert verdict.effect == EFFECT_PENALTY


def test_the_verdict_never_refuses():
    """The owner said `SAFA` is penalised, never rejected."""
    for row, days in ((WEST_AND_NORTH, 3), (WEST_AND_NORTH, 12),
                      (CENTRAL_ONLY, 12), ({}, 0)):
        assert safa_verdict(BOTH_CODES, row, days).softens is True


def test_the_rule_names_one_pair_and_generalises_to_no_other():
    """`BBKA` with `KABBBG` shares four sites and keeps its fault."""
    class Fault:
        statement = "day 3 (BBKA) and day 4 (KABBBG) share 4 sites: ..."

    assert verdict_for_fault(Fault(), ["BBKA", "KABBBG"], WEST_AND_NORTH, 12) is None


def test_a_fault_naming_both_codes_is_matched():
    class Fault:
        statement = "day 2 (SAMO) and day 9 (SAFA) share 3 sites: ..."

    assert verdict_for_fault(Fault(), BOTH_CODES, CENTRAL_ONLY, 12) is not None


# ── the rule as the judged book stores it ────────────────────────────────────

def test_the_stored_rule_carries_the_owner_words_that_produced_it():
    record = judged_rule_record()
    assert record.rule_id == SAFA_RULE_ID
    assert "SAMO" in record.comment_text
    assert "SAFA" in record.statement


def test_the_stored_rule_claims_no_counted_family():
    """
    The counter measures first nights, last nights, moves and trip lengths.
    None of those is a pair of template codes, so the corpus is silent and the
    record must not claim otherwise.
    """
    record = judged_rule_record()
    assert record.family == ""
    assert record.subject == ""
