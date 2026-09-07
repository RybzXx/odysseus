"""
tests/test_site_index.py

Tests for the site index: which sites a day holds, and when they shut.

The defect these guard against is a repeat that is not seen. Two templates name
one site under two spellings, a comparison on raw strings calls them different
sites, and a customer is driven to Mar Mattei twice. The catalogue holds both
spellings live today, so this is a defect the data already has and not one this
file invents.

Per tests/TESTING_STANDARD.md: no network, no mail, and no model. The index is
injected, so no test here depends on the pricing file on disk.
"""
import sys
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary import site_index  # noqa: E402
from services.itinerary.site_index import (  # noqa: E402
    Site,
    canonical_site_code,
    cities_the_templates_visit,
    repeated_sites,
    site_of,
    sites_in_city,
    sites_of_template,
    unindexed_codes,
    unplaceable_cities,
)

INDEX = {
    "NVH_MARK": Site("NVH_MARK", "Mar Mattei", "Baashiqa", "Northern Iraq", ("SUNDAY",)),
    "ERB_SORA": Site("ERB_SORA", "Soran", "Soran", "Northern Iraq", ()),
    "ERB_CITD": Site("ERB_CITD", "Erbil Citadel", "Erbil", "Northern Iraq", ("FRIDAY",)),
    "SA_G_MAL": Site("SA_G_MAL", "Grand Malwiyah", "Samarra", "Central Iraq", ()),
    "TRF_FEE": Site("TRF_FEE", "Transfer", "General", "", ()),
    "MO_ASR": Site("MO_ASR", "Ashur", "Salahdin", "Northern Iraq", ()),
}

TEMPLATES = {
    "A": {"included_sites": ["NVH_MARK", "ERB_CITD"]},
    "B": {"included_sites": ["NVHMARK"]},            # the catalogue's other spelling
    "C": {"included_sites": ["SA_G_MAL", "TRF_FEE"]},
    "D": {"included_sites": []},
    "E": {"included_sites": None},
    "F": {"included_sites": "ERB_SORA"},             # one code, not a list
    "G": {"included_sites": ["QQ_UNKNOWN", "MO_ASR"]},
}


@pytest.fixture(autouse=True)
def injected_index():
    """Every test reads INDEX, and leaves no cache behind."""
    before = site_index._INDEX
    site_index._INDEX = INDEX
    yield
    site_index._INDEX = before


# ── one spelling per site ────────────────────────────────────────────────────

def test_the_catalogue_spelling_becomes_the_index_spelling():
    assert canonical_site_code("NVHMARK") == "NVH_MARK"
    assert canonical_site_code("EB_SORA") == "ERB_SORA"


def test_a_code_already_in_the_index_spelling_is_left_alone():
    assert canonical_site_code("NVH_MARK") == "NVH_MARK"


def test_a_code_nothing_knows_passes_through_under_its_own_name():
    assert canonical_site_code("QQ_UNKNOWN") == "QQ_UNKNOWN"


def test_an_empty_code_stays_empty():
    assert canonical_site_code("") == ""
    assert canonical_site_code(None) == ""
    assert canonical_site_code("  ERB_CITD  ") == "ERB_CITD"


def test_a_site_is_found_under_either_spelling():
    assert site_of("NVHMARK") is site_of("NVH_MARK")
    assert site_of("NVH_MARK").site_name == "Mar Mattei"


def test_a_site_the_index_does_not_hold_is_none():
    assert site_of("QQ_UNKNOWN") is None
    assert site_of("") is None


# ── reading a template's sites ───────────────────────────────────────────────

def test_a_template_with_no_sites_gives_an_empty_list():
    assert sites_of_template(TEMPLATES["D"]) == []
    assert sites_of_template(TEMPLATES["E"]) == []


def test_one_code_written_as_a_string_is_read_as_one_site():
    assert sites_of_template(TEMPLATES["F"]) == ["ERB_SORA"]


def test_a_template_keeps_its_site_order():
    assert sites_of_template(TEMPLATES["A"]) == ["NVH_MARK", "ERB_CITD"]


def test_a_templates_codes_come_back_in_the_index_spelling():
    assert sites_of_template(TEMPLATES["B"]) == ["NVH_MARK"]


# ── the repeat itself ────────────────────────────────────────────────────────

def test_a_sequence_with_no_repeat_reports_none():
    assert repeated_sites(["C", "D"], TEMPLATES) == []


def test_an_empty_sequence_reports_no_repeat():
    assert repeated_sites([], TEMPLATES) == []
    assert repeated_sites(None, TEMPLATES) == []


def test_one_site_on_two_days_is_one_repeat():
    repeats = repeated_sites(["A", "A"], TEMPLATES)
    assert [r.site_code for r in repeats] == ["NVH_MARK", "ERB_CITD"]
    assert repeats[0].first_day == 1
    assert repeats[0].later_day == 2


def test_two_spellings_of_one_site_are_one_repeat():
    """The whole reason this module joins spellings."""
    repeats = repeated_sites(["A", "B"], TEMPLATES)
    assert [r.site_code for r in repeats] == ["NVH_MARK"]


def test_a_site_on_three_days_gives_two_repeats_both_naming_the_first():
    repeats = [r for r in repeated_sites(["B", "B", "B"], TEMPLATES)]
    assert [(r.first_day, r.later_day) for r in repeats] == [(1, 2), (1, 3)]


def test_a_day_the_catalogue_does_not_hold_contributes_no_repeat():
    assert repeated_sites(["A", "ZZZ", "A"], TEMPLATES)[0].later_day == 3


def test_a_repeat_states_the_site_name_and_both_days():
    statement = repeated_sites(["A", "B"], TEMPLATES)[0].statement
    assert "Mar Mattei" in statement
    assert "day 1" in statement and "day 2" in statement


# ── the cities behind the sites ──────────────────────────────────────────────

def test_the_index_spelling_of_a_city_becomes_the_map_spelling():
    visited = cities_the_templates_visit(TEMPLATES)
    assert "Bashiqa" in visited          # the index says Baashiqa
    assert "Baashiqa" not in visited


def test_a_city_the_map_cannot_place_is_left_out_and_named():
    visited = cities_the_templates_visit(TEMPLATES)
    assert "General" not in visited
    assert "Salahdin" not in visited
    stranded = dict(unplaceable_cities(TEMPLATES))
    assert stranded["General"] == ["TRF_FEE"]
    assert stranded["Salahdin"] == ["MO_ASR"]


def test_no_templates_visit_no_cities():
    assert cities_the_templates_visit({}) == set()


def test_the_sites_of_a_city_come_back_sorted():
    assert sites_in_city("Erbil") == ["ERB_CITD"]
    assert sites_in_city("erbil") == ["ERB_CITD"]
    assert sites_in_city("") == []
    assert sites_in_city("Atlantis") == []


def test_a_site_code_with_no_index_row_is_named():
    assert unindexed_codes(TEMPLATES) == ["QQ_UNKNOWN"]


# ── the index file on disk ───────────────────────────────────────────────────

def test_an_unreadable_index_gives_no_sites_rather_than_raising(monkeypatch, tmp_path):
    missing = tmp_path / "nothing.json"
    monkeypatch.setattr(site_index, "_INDEX", None)
    monkeypatch.setattr(site_index, "index_path", lambda: str(missing))
    assert site_index.load_sites(force_reload=True) == {}


def test_a_malformed_row_is_skipped_and_the_rest_are_kept(monkeypatch, tmp_path):
    path = tmp_path / "tickets.json"
    path.write_text(
        '[{"site_code": "OK_ONE", "site_name": "One", "city": "Erbil"},'
        ' "not a row", {"no_site_code": true},'
        ' {"site_code": "OK_TWO", "city": "Mosul", "closed_on": ["friday"]}]',
        encoding="utf-8")
    monkeypatch.setattr(site_index, "_INDEX", None)
    monkeypatch.setattr(site_index, "index_path", lambda: str(path))
    sites = site_index.load_sites(force_reload=True)
    assert sorted(sites) == ["OK_ONE", "OK_TWO"]
    assert sites["OK_TWO"].closed_on == ("FRIDAY",)
