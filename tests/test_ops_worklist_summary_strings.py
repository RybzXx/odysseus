"""The worklist summary must not render placeholders or double units.

Bil Weekend's intake sources do not use NULL for a field nobody filled in.
The data-entry team types "Not known" into a queue column, the intake form
concatenates a country-code sign onto it ("+Not known"), and the free-text
trip_days column already carries its own unit ("10 days"). The composer used
to pass all three straight through: it filtered summary elements on
truthiness alone, which keeps every non-empty placeholder, and it appended
" days" unconditionally, which produced "10 days days".

Every value in these fixtures was read from the live queue_requests table on
2026-09-02, not invented — including the trailing space in "Not Known ",
which is why a bare == comparison against "Not known" is not enough.

These tests are what makes a regression to truthiness-filtering loud.
"""

import asyncio

import pytest

from mcp_servers import ops_server
from mcp_servers.ops_server import (
    _day_count_summary,
    _fetch_merged_worklist,
    _is_empty_value,
    _phone_display,
)

# Exactly as stored, read from the live table.
LIVE_PLACEHOLDERS = ["Not Known", "Not Known ", "Not known ", "+Not known"]
LIVE_REAL_VALUES = ["10 days", "6 days", "B2C", "- Tour/Full service", "2026-10-23"]


@pytest.mark.parametrize("value", LIVE_PLACEHOLDERS)
def test_live_placeholders_are_empty(value):
    """Casing varies and one carries a trailing space; all mean 'blank'."""
    assert _is_empty_value(value) is True


@pytest.mark.parametrize("value", LIVE_REAL_VALUES)
def test_live_real_values_survive(value):
    """The leading '-' on service_type is a bullet in Bil Weekend's own data,
    not a placeholder prefix — suppressing it would delete real information."""
    assert _is_empty_value(value) is False


def test_placeholder_is_matched_whole_not_as_a_substring():
    """A real value that merely contains the placeholder text must survive."""
    assert _is_empty_value("Not known Road, Baghdad") is False


def test_day_count_does_not_double_the_unit():
    """The queue's trip_days is free text and usually already says "days"."""
    assert _day_count_summary("10 days") == "10 days"
    assert _day_count_summary("6 days") == "6 days"
    assert _day_count_summary("1 day") == "1 day"


def test_day_count_adds_the_unit_to_a_bare_number():
    assert _day_count_summary(10) == "10 days"
    assert _day_count_summary("7") == "7 days"


def test_day_count_suppresses_a_placeholder_instead_of_uniting_it():
    """"Not Known " must not become "Not Known  days"."""
    assert _day_count_summary("Not Known ") is None
    assert _day_count_summary(None) is None


def test_phone_display_suppresses_the_placeholder_but_keeps_a_real_number():
    assert _phone_display(None, "+Not known") is None
    assert _phone_display("+964", "7512345678") == "+964 7512345678"


def _queue_row():
    """One live queue row, values verbatim from the 2026-09-02 read."""
    return {
        "row_id": "qr-mtjze8ki-2e63fa17",
        "service_type": "- Tour/Full service",
        "request_type": "B2C",
        "regions": "Not Known",
        "trip_days": "Not known ",
        "travel_date": "2026-11-01",
        "phone": "+Not known",
        "full_name": "Test Submitter",
        "customer_email": "someone@example.com",
        "status": "New",
    }


@pytest.fixture
def worklist_of_one_queue_row(monkeypatch):
    """Drive the real composer with only the queue populated."""

    async def fake_sb_request(method, table, params=None, json_body=None, prefer=None):
        return [_queue_row()] if table == "queue_requests" else []

    monkeypatch.setattr(ops_server, "_sb_request", fake_sb_request)
    return asyncio.run(_fetch_merged_worklist())


def test_composed_summary_drops_every_placeholder(worklist_of_one_queue_row):
    """regions and trip_days are placeholders; only the real fields remain."""
    (row,) = worklist_of_one_queue_row
    assert row["summary"] == ["- Tour/Full service", "B2C", "2026-11-01"]


def test_composed_row_drops_a_placeholder_phone(worklist_of_one_queue_row):
    """"+Not known" reached the contact line because filter(Boolean) keeps it."""
    (row,) = worklist_of_one_queue_row
    assert row["phone"] is None


def test_composed_summary_never_doubles_the_unit(worklist_of_one_queue_row):
    """The pre-fix composer produced "Not known  days" for this row."""
    (row,) = worklist_of_one_queue_row
    assert not any("days days" in s or "known" in s.casefold() for s in row["summary"])
