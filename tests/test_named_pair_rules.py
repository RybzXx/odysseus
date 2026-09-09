"""
tests/test_named_pair_rules.py

Alternative pairs: two templates that sell one day two ways.

These replace the tests for `judged--safa-with-samo`, which ws-03 phase seven
retired. That rule asked whether a request named the west and the north, and
"nineveh plain" sat in both of its word lists, so the label "Western Iraq &
Nineveh Plains" satisfied both halves of an `and` by itself. Its eight-day
threshold sat below the one sold precedent, which runs eleven.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.itinerary.named_pair_rules import (  # noqa: E402
    ALTERNATIVE_PAIRS,
    EFFECT_ALTERNATIVE,
    alternative_of,
    pairs_in,
    verdict_for_fault,
)


class _Fault:
    def __init__(self, statement):
        self.statement = statement


def test_every_pair_names_two_codes_and_states_why():
    for pair, statement in ALTERNATIVE_PAIRS.items():
        assert len(pair) == 2
        assert statement.strip()
        for code in pair:
            assert code in statement, f"{statement!r} does not name {code}"


@pytest.mark.parametrize("code,other", [
    ("SAFA", "BGFA"), ("BGFA", "SAFA"),
    ("MO1", "MO1EB"), ("MO1EB", "MO1"),
    ("NA2BA", "NA2BG"), ("NA2BG", "NA2BA"),
])
def test_alternative_of_answers_both_ways(code, other):
    assert alternative_of(code) == other


def test_a_code_in_no_pair_has_no_alternative():
    assert alternative_of("ARRBG") is None
    assert alternative_of("") is None


def test_pairs_in_finds_a_sequence_holding_both_halves():
    found = pairs_in(["ARRBG", "SAFA", "BG1CT", "BGFA"])
    assert len(found) == 1
    first, second, statement = found[0]
    assert (first, second) == ("SAFA", "BGFA")
    assert "Samarra" in statement


def test_pairs_in_is_quiet_when_only_one_half_is_present():
    assert pairs_in(["ARRBG", "SAFA", "SAMO"]) == []
    assert pairs_in(["MO1EB"]) == []
    assert pairs_in([]) == []


def test_pairs_in_finds_more_than_one_pair():
    assert len(pairs_in(["SAFA", "BGFA", "MO1", "MO1EB"])) == 2


def test_a_verdict_about_a_pair_never_softens_the_fault():
    verdict = verdict_for_fault(
        _Fault("day 2 (SAFA) and day 3 (BGFA) share one site: Agirguf"),
        ["SAFA", "BGFA"], {}, 3)
    assert verdict is not None
    assert verdict.effect == EFFECT_ALTERNATIVE
    assert verdict.softens is False
    assert verdict.lowers_the_score is True


def test_no_verdict_for_a_fault_about_other_codes():
    assert verdict_for_fault(_Fault("day 7 (SAMO) and day 8 (SAFA) share 3 sites"),
                             ["SAMO", "SAFA"], {}, 10) is None


def test_samo_beside_safa_is_no_longer_excused():
    """The retired rule turned this fault into a flag. Nothing does now."""
    west_and_north = {"regions": ["Western Iraq & Nineveh Plains"]}
    for days in (3, 8, 12):
        assert verdict_for_fault(
            _Fault("day 6 (SAFA) and day 7 (SAMO) share 3 sites"),
            ["SAFA", "SAMO"], west_and_north, days) is None
