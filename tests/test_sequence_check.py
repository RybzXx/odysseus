"""
tests/test_sequence_check.py

Tests for the sequence check: what is wrong with a proposed itinerary.

Two defects these guard against. A check that passes a sequence it never tested
reads the same as a check that tested it and found nothing, and a reviewer
cannot tell the two apart. A check that refuses a leg the work drives every
week trains a reviewer to ignore it, which costs more than not running it.

Per tests/TESTING_STANDARD.md: no network, no mail, and no model. The counted
corpus and the site index are both injected.
"""
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary import move_map, site_index  # noqa: E402
from services.itinerary.sequence_check import (  # noqa: E402
    FAULT_DAY_REPEAT,
    FAULT_FLAG_CAP,
    FAULT_LEG_TOO_LONG,
    FAULT_MOVE_NOT_JOINED,
    FAULT_SITE_CLOSED,
    FAULT_SITE_REPEAT,
    FLAG_CAP,
    check_sequence,
    format_check,
)
from services.itinerary.site_index import Site  # noqa: E402

CORPUS = Counter({
    ("Baghdad", "Mosul"): 171,
    ("Mosul", "Duhok"): 61,
    ("Mosul", "Erbil"): 53,
    ("Sulaymaniyah", "Erbil"): 19,
})

INDEX = {
    "ERB_CITD": Site("ERB_CITD", "Erbil Citadel", "Erbil", "Northern Iraq", ("FRIDAY",)),
    "SA_G_MAL": Site("SA_G_MAL", "Grand Malwiyah", "Samarra", "Central Iraq", ()),
    "MO_HTR": Site("MO_HTR", "Hatra", "Hatra", "Northern Iraq", ()),
}

# Each template names the cities its day passes through, in order, because
# `day_shape` reads that field to say where the day sets off. A template with an
# overnight city and no chain reads as a city day that starts where it sleeps,
# and the day-start check then refuses a transit for arriving from anywhere
# (ws-03 phase seven, WP33.2).
TEMPLATES = {
    "BAGHDAD_DAY": {"city": "Baghdad", "overnight_city": "Baghdad",
                    "included_sites": []},
    "TO_MOSUL": {"city": "Baghdad / Samarra / Mosul", "overnight_city": "Mosul",
                 "included_sites": ["SA_G_MAL", "MO_HTR"]},
    "BACK_TO_BAGHDAD": {"city": "Mosul / Samarra / Baghdad",
                        "overnight_city": "Baghdad",
                        "included_sites": ["SA_G_MAL"]},
    "MOSUL_DAY": {"city": "Mosul", "overnight_city": "Mosul",
                  "included_sites": []},
    "TO_DUHOK": {"city": "Mosul / Duhok", "overnight_city": "Duhok",
                 "included_sites": []},
    "TO_SULAY": {"city": "Mosul / Sulaymaniyah",
                 "overnight_city": "Sulaymaniyah", "included_sites": []},
    "TO_ERBIL": {"city": "Mosul / Erbil", "overnight_city": "Erbil",
                 "included_sites": ["ERB_CITD"]},
    "ERBIL_DAY_TWO": {"city": "Erbil", "overnight_city": "Erbil",
                      "included_sites": ["ERB_CITD"]},
    "SAME_SITES_AS_MOSUL": {"city": "Samarra / Mosul", "overnight_city": "Mosul",
                            "included_sites": ["SA_G_MAL", "MO_HTR"]},
    "ERBIL_DAY": {"city": "Erbil", "overnight_city": "Erbil",
                  "included_sites": ["ERB_CITD"]},
    "TO_BASRA": {"city": "Duhok / Basra", "overnight_city": "Basra",
                 "included_sites": []},
    "DEPARTURE": {"city": "Baghdad", "overnight_city": "", "included_sites": []},
}


@pytest.fixture(autouse=True)
def injected_sources():
    counted_before, index_before = move_map._COUNTED_MOVES, site_index._INDEX
    move_map._COUNTED_MOVES, site_index._INDEX = CORPUS, INDEX
    yield
    move_map._COUNTED_MOVES, site_index._INDEX = counted_before, index_before


def kinds(check):
    return [fault.kind for fault in check.faults]


# ── nothing to check ─────────────────────────────────────────────────────────

def test_an_empty_sequence_raises_no_fault():
    check = check_sequence([], TEMPLATES, start_date=date(2026, 1, 1))
    assert check.faults == []
    assert check.nights == []


def test_a_sequence_of_none_is_read_as_empty():
    assert check_sequence(None, TEMPLATES, start_date=date(2026, 1, 1)).faults == []


def test_an_empty_sequence_is_never_reported_clean():
    """
    Six of the eleven live drafts hold no codes. Every check passes on nothing,
    so a clean verdict would tell a reviewer an empty proposal was examined.
    """
    check = check_sequence([], TEMPLATES, start_date=date(2026, 1, 1))
    assert check.found_no_fault is True
    assert check.is_fully_checked is False
    assert check.is_clean is False
    assert any("no day codes" in note for note in check.untested)


def test_a_code_the_catalogue_does_not_hold_is_named_and_not_a_fault():
    check = check_sequence(["ZZZ", "BAGHDAD_DAY"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert check.unknown_codes == ["ZZZ"]
    assert check.faults == []


def test_a_departure_day_takes_no_night():
    check = check_sequence(["BAGHDAD_DAY", "DEPARTURE"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert check.nights == ["Baghdad"]


# ── a site on two days ───────────────────────────────────────────────────────

def test_one_shared_site_is_a_flag_and_not_a_fault():
    """One site is a flag. The owner reads it and decides (D30)."""
    check = check_sequence(["TO_MOSUL", "BACK_TO_BAGHDAD"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert FAULT_SITE_REPEAT not in kinds(check)
    assert [f.site_code for f in check.flags] == ["SA_G_MAL"]
    assert check.flags[0].day == 2


def test_two_shared_sites_are_one_fault_about_the_day_pair():
    """
    The unit is the day pair, not the site. Four shared sites is one fault
    about two days, because a reviewer decides about two days.
    """
    check = check_sequence(["TO_MOSUL", "SAME_SITES_AS_MOSUL"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    repeats = [f for f in check.faults if f.kind == FAULT_SITE_REPEAT]
    assert len(repeats) == 1
    assert repeats[0].day == 2
    assert "2 sites" in repeats[0].statement


def test_a_sequence_that_visits_each_site_one_time_has_no_repeat():
    check = check_sequence(["TO_MOSUL", "TO_DUHOK"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert FAULT_SITE_REPEAT not in kinds(check)
    assert check.flags == []


def test_the_rule_reads_any_two_days_and_not_adjacent_days_alone():
    """`SAMO` on day 2 and `SAFA` on day 9 repeat Samarra just the same."""
    check = check_sequence(
        ["TO_MOSUL", "MOSUL_DAY", "MOSUL_DAY", "BACK_TO_BAGHDAD"], TEMPLATES,
        start_date=date(2026, 1, 1))
    assert [f.day for f in check.flags] == [4]


def test_the_same_template_twice_is_a_fault_whatever_the_site_count():
    """One shared site would be a flag. The same day again is a fault (D32)."""
    check = check_sequence(["TO_ERBIL", "MOSUL_DAY", "TO_ERBIL"], TEMPLATES,
                           start_date=date(2026, 9, 12))
    repeats = [f for f in check.faults if f.kind == FAULT_DAY_REPEAT]
    assert [f.day for f in repeats] == [3]
    assert check.flags == []


def test_two_flags_break_the_cap_and_raise_a_fault():
    """Two day pairs each sharing one site reaches FLAG_CAP (D31)."""
    check = check_sequence(
        ["TO_MOSUL", "BACK_TO_BAGHDAD", "TO_ERBIL", "ERBIL_DAY_TWO"], TEMPLATES,
        start_date=date(2026, 9, 12))
    assert len(check.flags) == FLAG_CAP
    assert FAULT_FLAG_CAP in kinds(check)


def test_one_flag_does_not_break_the_cap():
    check = check_sequence(["TO_MOSUL", "BACK_TO_BAGHDAD"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert len(check.flags) == 1
    assert FAULT_FLAG_CAP not in kinds(check)


# ── a move the work has never carried ────────────────────────────────────────

def test_a_pair_the_corpus_never_joins_is_a_fault():
    check = check_sequence(["MOSUL_DAY", "TO_SULAY"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert FAULT_MOVE_NOT_JOINED in kinds(check)


def test_a_pair_the_corpus_joins_is_no_fault():
    check = check_sequence(["BAGHDAD_DAY", "TO_MOSUL"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert FAULT_MOVE_NOT_JOINED not in kinds(check)


def test_two_nights_in_one_city_are_no_move_at_all():
    check = check_sequence(["MOSUL_DAY", "MOSUL_DAY"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert FAULT_MOVE_NOT_JOINED not in kinds(check)


def test_a_pair_the_corpus_carries_one_way_is_joined_both_ways():
    """
    The corpus carries Mosul to Duhok 61 times and Duhok to Mosul never. That
    is one road of 69 km, so the check accepts it either way.
    """
    check = check_sequence(["TO_DUHOK", "MOSUL_DAY"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert FAULT_MOVE_NOT_JOINED not in kinds(check)


def test_a_pair_the_corpus_carries_neither_way_is_still_refused():
    """Mosul to Sulaymaniyah is zero each way, and stays a fault."""
    check = check_sequence(["MOSUL_DAY", "TO_SULAY"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert FAULT_MOVE_NOT_JOINED in kinds(check)
    refusal = [f for f in check.faults if f.kind == FAULT_MOVE_NOT_JOINED][0]
    assert "either direction" in refusal.statement


# ── a leg longer than the work drives ────────────────────────────────────────

def test_a_leg_over_the_ceiling_is_a_fault():
    check = check_sequence(["TO_DUHOK", "TO_BASRA"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert FAULT_LEG_TOO_LONG in kinds(check)


def test_a_short_leg_is_no_fault():
    check = check_sequence(["TO_MOSUL", "TO_DUHOK"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert FAULT_LEG_TOO_LONG not in kinds(check)


def test_a_leg_can_be_both_unjoined_and_too_long_and_says_both():
    check = check_sequence(["TO_DUHOK", "TO_BASRA"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    assert kinds(check).count(FAULT_MOVE_NOT_JOINED) == 1
    assert kinds(check).count(FAULT_LEG_TOO_LONG) == 1


def test_the_fault_names_both_cities_and_the_distance():
    fault = [f for f in check_sequence(["TO_DUHOK", "TO_BASRA"], TEMPLATES,
                                       start_date=date(2026, 1, 1)).faults
             if f.kind == FAULT_LEG_TOO_LONG][0]
    assert fault.from_city == "Duhok" and fault.to_city == "Basra"
    assert fault.km > 900


# ── a site that is shut ──────────────────────────────────────────────────────

def test_a_site_shut_on_the_weekday_its_day_lands_on_is_a_fault():
    # 2026-09-10 is a Thursday, so day 2 is the Friday the Citadel is shut.
    check = check_sequence(["BAGHDAD_DAY", "TO_ERBIL"], TEMPLATES,
                           start_date=date(2026, 9, 10))
    closed = [f for f in check.faults if f.kind == FAULT_SITE_CLOSED]
    assert [f.day for f in closed] == [2]


def test_the_same_site_on_another_weekday_is_no_fault():
    check = check_sequence(["BAGHDAD_DAY", "TO_ERBIL"], TEMPLATES,
                           start_date=date(2026, 9, 12))
    assert FAULT_SITE_CLOSED not in kinds(check)


def test_a_start_date_given_as_a_datetime_is_read_the_same_way():
    check = check_sequence(["BAGHDAD_DAY", "TO_ERBIL"], TEMPLATES,
                           start_date=datetime(2026, 9, 10, 14, 30))
    assert FAULT_SITE_CLOSED in kinds(check)


def test_with_no_start_date_the_closing_check_records_that_it_did_not_run():
    check = check_sequence(["BAGHDAD_DAY", "TO_ERBIL"], TEMPLATES)
    assert FAULT_SITE_CLOSED not in kinds(check)
    assert any("start date" in note for note in check.untested)


# ── what "clean" is allowed to mean ──────────────────────────────────────────

def test_a_sequence_with_a_check_that_did_not_run_is_not_reported_clean():
    """
    Nothing tested the closing days, because the request carries no start date.
    A caller that gates on `is_clean` would send this to a customer having
    checked three of the four things this module names.

    One day, so no move and no repeat can raise a fault and hide the question.
    """
    check = check_sequence(["TO_ERBIL"], TEMPLATES)
    assert check.faults == []
    assert check.untested
    assert check.is_clean is False


def test_a_sequence_with_every_check_run_and_nothing_found_is_clean():
    check = check_sequence(["BAGHDAD_DAY", "TO_MOSUL"], TEMPLATES,
                           start_date=date(2026, 9, 12))
    assert check.untested == []
    assert check.is_clean is True


# ── the report a reviewer reads ──────────────────────────────────────────────

def test_the_report_names_every_fault_it_found():
    check = check_sequence(["TO_MOSUL", "BACK_TO_BAGHDAD"], TEMPLATES,
                           start_date=date(2026, 1, 1))
    text = format_check(check)
    assert "Grand Malwiyah" in text
    assert str(len(check.faults)) in text


def test_the_report_of_a_clean_sequence_still_names_what_is_not_yet_checked():
    text = format_check(check_sequence(["BAGHDAD_DAY"], TEMPLATES,
                                       start_date=date(2026, 1, 1)))
    assert "sites_skipped" in text
    assert "day_trip_on_a_moving_day" in text
    assert "day_start" not in text, "day_start is built now, so it is not pending"
