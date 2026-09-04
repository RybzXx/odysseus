"""
tests/test_offers_apply.py

Tests for services/offers/apply_to_sheet.py — the only code that changes the
day-template catalogue.

Every test runs against a fake spreadsheet. Nothing here touches Google, and
that is a hard rule rather than a convenience: this module's failure mode is
damaging the live catalogue, so its tests must never be able to.
"""
import sys
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.offers import apply_to_sheet as sheet  # noqa: E402
from services.offers import proposals as prop  # noqa: E402
from services.offers.catalogue import TEMPLATE_FIELDS  # noqa: E402


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(prop, "TEMPLATE_PROPOSAL_DIR", str(tmp_path / "proposals"))
    return tmp_path


class _Call:
    def __init__(self, payload):
        self.payload = payload

    def execute(self, **_):
        return self.payload


class _Values:
    def __init__(self, owner):
        self.owner = owner

    def get(self, spreadsheetId=None, range=None):
        return _Call({"values": self.owner.grid()})

    def clear(self, spreadsheetId=None, range=None):
        if self.owner.read_only:
            raise RuntimeError("caller has no edit rights")
        return _Call({})

    def update(self, spreadsheetId=None, range=None, valueInputOption=None, body=None):
        self.owner.updates.append((range, body["values"][0]))
        return _Call({})

    def append(self, spreadsheetId=None, range=None, valueInputOption=None,
               insertDataOption=None, body=None):
        self.owner.appended.extend(body["values"])
        return _Call({})


class _FakeSheets:
    """A spreadsheet just real enough to exercise preflight and the writes."""

    def __init__(self, rows=None, merges=(), header=None, read_only=False, tab="templates"):
        self.header = list(header or TEMPLATE_FIELDS)
        self.rows = list(rows or [])
        self.merges = list(merges)
        self.read_only = read_only
        self.tab = tab
        self.updates = []
        self.appended = []

    def get(self, spreadsheetId=None):
        return _Call({"sheets": [{"properties": {"title": self.tab}, "merges": self.merges}]})

    def values(self):
        return _Values(self)

    def grid(self):
        if not self.header:
            return []          # Sheets returns no values at all for an empty tab
        return [self.header] + self.rows + self.appended


def _row(code, text="old text", header=None):
    header = header or TEMPLATE_FIELDS
    values = {name: "" for name in TEMPLATE_FIELDS}
    values.update(code=code, full_text=text, active="FALSE", needs_review="TRUE")
    return [values[name] for name in header]


def _fields(code="MARSH", text="Drive south to the marshes and return by sunset."):
    values = {name: "" for name in TEMPLATE_FIELDS}
    values.update(code=code, full_text=text, overnight_city="Nasiriyah",
                  included_sites_json="[]", pricing_tags_json="[]",
                  active=False, needs_review=True)
    return values


def _approved(kind=prop.KIND_NEW, code="MARSH", text=None, target_code=None):
    fields = _fields(code=code) if text is None else _fields(code=code, text=text)
    proposal = prop.build_proposal(kind, fields, ["<1@x>#1"], target_code=target_code)
    prop.save(proposal)
    prop.record_verdict(proposal.proposal_id, prop.STATUS_APPROVED)
    return proposal.proposal_id


# ── Preflight refuses before it writes ────────────────────────────────────────

def test_preflight_refuses_a_merged_range():
    with pytest.raises(sheet.SheetApplyError, match="merged"):
        sheet.preflight("sid", _FakeSheets(rows=[_row("MO1")], merges=[{"startRowIndex": 25}]))


def test_preflight_refuses_a_missing_tab():
    with pytest.raises(sheet.SheetApplyError, match="no 'templates' tab"):
        sheet.preflight("sid", _FakeSheets(tab="something_else"))


def test_preflight_refuses_a_header_missing_catalogue_fields():
    with pytest.raises(sheet.SheetApplyError, match="header is missing"):
        sheet.preflight("sid", _FakeSheets(header=["code", "title"]))


def test_preflight_refuses_an_empty_tab():
    empty = _FakeSheets()
    empty.header = []
    with pytest.raises(sheet.SheetApplyError, match="no header row"):
        sheet.preflight("sid", empty)


def test_preflight_refuses_when_it_cannot_write():
    with pytest.raises(sheet.SheetApplyError, match="no write access"):
        sheet.preflight("sid", _FakeSheets(rows=[_row("MO1")], read_only=True))


def test_preflight_maps_codes_to_their_sheet_rows():
    state = sheet.preflight("sid", _FakeSheets(rows=[_row("MO1"), _row("BG1")]))
    assert state["row_by_code"] == {"MO1": 2, "BG1": 3}
    assert state["row_count"] == 2


# ── Writing ───────────────────────────────────────────────────────────────────

def test_dry_run_is_the_default_and_writes_nothing(queue):
    proposal_id = _approved()
    fake = _FakeSheets(rows=[_row("MO1")])

    plan = sheet.apply_approved("sid", service=fake)

    assert plan["dry_run"] is True
    assert len(plan["appends"]) == 1 and plan["written"] == 0
    assert fake.appended == [] and fake.updates == []
    assert prop.load(proposal_id).applied_at is None


def test_applying_appends_a_new_template_and_marks_it(queue):
    proposal_id = _approved()
    fake = _FakeSheets(rows=[_row("MO1")])

    plan = sheet.apply_approved("sid", dry_run=False, service=fake)

    assert plan["written"] == 1 and plan["verified"] == 1
    assert fake.appended[0][TEMPLATE_FIELDS.index("code")] == "MARSH"
    assert prop.load(proposal_id).applied_at is not None


def test_rows_follow_the_sheets_own_column_order(queue):
    """An inserted or reordered column must move our values with it."""
    _approved()
    shuffled = list(reversed(TEMPLATE_FIELDS))
    fake = _FakeSheets(rows=[], header=shuffled)

    sheet.apply_approved("sid", dry_run=False, service=fake)

    assert fake.appended[0][shuffled.index("code")] == "MARSH"
    assert fake.appended[0][shuffled.index("full_text")].startswith("Drive south")


def test_an_applied_proposal_is_never_written_twice(queue):
    _approved()
    sheet.apply_approved("sid", dry_run=False, service=_FakeSheets(rows=[]))

    second = _FakeSheets(rows=[])
    assert sheet.apply_approved("sid", dry_run=False, service=second)["written"] == 0
    assert second.appended == []


def test_a_revision_updates_its_target_row_in_place(queue):
    _approved(kind=prop.KIND_REVISION, code="MO1", text="new wording", target_code="MO1")
    fake = _FakeSheets(rows=[_row("BG1"), _row("MO1")])

    plan = sheet.apply_approved("sid", dry_run=False, service=fake)

    assert len(plan["updates"]) == 1 and fake.appended == []
    written_range, written_row = fake.updates[0]
    assert written_range.startswith("templates!A3:"), "MO1 is the sheet's third row"
    assert written_row[TEMPLATE_FIELDS.index("full_text")] == "new wording"


# ── Refusals that protect the catalogue ───────────────────────────────────────

def test_an_approved_proposal_with_no_code_is_skipped_not_written(queue):
    _approved(code="")
    plan = sheet.apply_approved("sid", dry_run=False, service=_FakeSheets(rows=[_row("MO1")]))
    assert plan["appends"] == [] and plan["written"] == 0
    assert plan["skipped"][0]["reason"] == "approved without a code"


def test_a_revision_whose_target_vanished_is_skipped(queue):
    _approved(kind=prop.KIND_REVISION, code="GONE", target_code="GONE")
    plan = sheet.apply_approved("sid", dry_run=False, service=_FakeSheets(rows=[_row("MO1")]))
    assert plan["updates"] == []
    assert "not in the sheet" in plan["skipped"][0]["reason"]


def test_a_new_template_reusing_an_existing_code_is_refused(queue):
    _approved(code="MO1")
    plan = sheet.apply_approved("sid", dry_run=False, service=_FakeSheets(rows=[_row("MO1")]))
    assert plan["appends"] == []
    assert "already exists" in plan["skipped"][0]["reason"]


def test_a_pending_proposal_is_never_written(queue):
    proposal = prop.build_proposal(prop.KIND_NEW, _fields(), ["<1@x>#1"])
    prop.save(proposal)
    fake = _FakeSheets(rows=[])
    assert sheet.apply_approved("sid", dry_run=False, service=fake)["written"] == 0
    assert fake.appended == []


def test_a_rejected_proposal_is_never_written(queue):
    proposal = prop.build_proposal(prop.KIND_NEW, _fields(), ["<1@x>#1"])
    prop.save(proposal)
    prop.record_verdict(proposal.proposal_id, prop.STATUS_REJECTED)
    fake = _FakeSheets(rows=[])
    assert sheet.apply_approved("sid", dry_run=False, service=fake)["written"] == 0


def test_written_rows_land_inactive_and_flagged(queue):
    """Invariant 1.3 — nothing reaches the catalogue live."""
    _approved()
    fake = _FakeSheets(rows=[])
    sheet.apply_approved("sid", dry_run=False, service=fake)
    row = fake.appended[0]
    assert row[TEMPLATE_FIELDS.index("active")] == "FALSE"
    assert row[TEMPLATE_FIELDS.index("needs_review")] == "TRUE"


def test_only_named_proposals_are_written(queue):
    wanted = _approved(code="MARSH")
    _approved(code="OTHER", text="A different day entirely, written once.")
    fake = _FakeSheets(rows=[])

    plan = sheet.apply_approved("sid", dry_run=False, service=fake, only=[wanted])

    assert plan["written"] == 1
    assert fake.appended[0][TEMPLATE_FIELDS.index("code")] == "MARSH"


def test_column_letters_survive_past_z():
    assert sheet._column_letter(0) == "A"
    assert sheet._column_letter(25) == "Z"
    assert sheet._column_letter(26) == "AA"
    assert sheet._column_letter(27) == "AB"
