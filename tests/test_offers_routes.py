"""
tests/test_offers_routes.py

Tests for routes/offers/offers_routes.py — the catalogue-gap review surface.

Handlers are driven directly rather than through TestClient, per
tests/TESTING_STANDARD.md: no FastAPI app import, no SQLite, no network. The
admin gate is replaced with a no-op so these tests exercise handler behaviour
rather than re-testing the gate, which has its own coverage.
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from routes.offers import offers_routes  # noqa: E402
from services.offers import proposals as prop  # noqa: E402
from services.offers.catalogue import TEMPLATE_FIELDS  # noqa: E402
from services.offers.models import OfferDay, SentOffer  # noqa: E402

TEXT_MOSUL = (
    "8 AM Start the day with discovering the reconstruction of the old city, "
    "especially Al-Nuri Mosque and Al Hadbaa Minaret. Walk through the area where "
    "the last and most intensive battle took place. Lunch with locals."
)
TEXT_MARSHES = (
    "Drive south to the marshes, board a mashoof through the reed channels, "
    "and return to the hotel before sunset."
)


class _Request:
    """Stand-in for the Request the admin gate would inspect."""


def _handlers():
    return {route.name: route.endpoint for route in offers_routes.setup_offers_routes().routes}


def _call(name, **kwargs):
    return asyncio.run(_handlers()[name](request=_Request(), **kwargs))


@pytest.fixture(autouse=True)
def open_gate(monkeypatch):
    monkeypatch.setattr(offers_routes, "require_admin", lambda request: None)


@pytest.fixture
def queue(tmp_path, monkeypatch):
    from services.offers import gap_report, offer_store
    monkeypatch.setattr(prop, "TEMPLATE_PROPOSAL_DIR", str(tmp_path / "proposals"))
    monkeypatch.setattr(gap_report, "GAP_SUMMARY_FILE", str(tmp_path / "catalogue_gap.json"))
    # The handlers stamp what they derive, and the stamp reads the corpus
    # directory. Without this the fingerprint is taken over the real corpus and
    # the result depends on the machine the tests run on.
    monkeypatch.setattr(offer_store, "OFFER_CORPUS_DIR", str(tmp_path / "offer_corpus"))
    return tmp_path


@pytest.fixture
def corpus(monkeypatch):
    """Two offers: one day the catalogue has, two days of one pattern it lacks."""
    offers = [
        SentOffer(message_id="<1@x>", subject="10 Days in Iraq", sent_at=None,
                  attachment_name="offer.docx",
                  days=[OfferDay(1, TEXT_MOSUL, "Mosul"),
                        OfferDay(2, TEXT_MARSHES, "Nasiriyah")]),
        SentOffer(message_id="<2@x>", subject="Marshes trip", sent_at=None,
                  attachment_name="offer2.docx",
                  days=[OfferDay(1, TEXT_MARSHES, "Nasiriyah")]),
    ]
    monkeypatch.setattr(offers_routes, "iter_offers", lambda: iter(offers))
    # The evidence handler looks up one message rather than walking the corpus,
    # so the fixture answers that lookup from the same offers.
    monkeypatch.setattr(offers_routes, "offers_of_message",
                        lambda message_id: [o for o in offers if o.message_id == message_id])
    monkeypatch.setattr(offers_routes, "load_template_texts", lambda: {"MO1": TEXT_MOSUL})
    return offers


def _fields(text=TEXT_MARSHES):
    base = {name: "" for name in TEMPLATE_FIELDS}
    base.update(code="", full_text=text, overnight_city="Nasiriyah",
                included_sites_json="[]", pricing_tags_json="[]",
                active=False, needs_review=True)
    return base


# ── Gap ───────────────────────────────────────────────────────────────────────

def test_gap_says_so_when_it_has_never_been_measured(queue, corpus):
    assert _call("get_catalogue_gap")["measured"] is False


def test_rebuild_measures_the_gap_and_the_page_reads_that_measurement(queue, corpus):
    """
    The reviewer must see the gap the queue came from. Recomputing per request
    took minutes over a real corpus and timed the page out, and a fresh number
    beside a stale queue would disagree with it silently.
    """
    built = _call("rebuild_proposals")["gap"]
    assert built["offers"] == 2 and built["total_days"] == 3
    assert built["matched"] + built["near_miss"] + built["unmatched"] == built["total_days"]
    assert built["coverage"] == pytest.approx(1 / 3, abs=1e-4)

    served = _call("get_catalogue_gap")
    assert served["measured"] is True
    assert {k: served[k] for k in built} == built, "the page shows exactly what was measured"


def test_gap_separates_never_matched_from_never_referenced(queue, corpus, monkeypatch):
    monkeypatch.setattr(offers_routes, "load_template_texts",
                        lambda: {"MO1": TEXT_MOSUL, "UNUSED": "Fly to Sulaymaniyah at dawn."})
    _call("rebuild_proposals")
    gap = _call("get_catalogue_gap")
    assert "UNUSED" in gap["never_matched_codes"]
    assert "UNUSED" in gap["never_referenced_codes"]
    assert "MO1" not in gap["never_matched_codes"]


# ── Rebuilding the queue ──────────────────────────────────────────────────────

def test_rebuild_refuses_an_empty_corpus(queue, monkeypatch):
    monkeypatch.setattr(offers_routes, "iter_offers", lambda: iter([]))
    with pytest.raises(HTTPException) as raised:
        _call("rebuild_proposals")
    assert raised.value.status_code == 409


def test_rebuild_drafts_a_proposal_for_the_repeated_unmatched_day(queue, corpus):
    result = _call("rebuild_proposals")
    assert result["drafted"] == 1
    assert result["queue"][prop.STATUS_PENDING] == 1
    listed = _call("list_proposals", status=None, kind=None)["proposals"][0]
    assert listed["kind"] == prop.KIND_NEW
    assert listed["occurrences"] == 2
    assert listed["nearest_code"] == "MO1"
    assert listed["status"] == prop.STATUS_PENDING


def test_rebuild_is_idempotent_and_never_reopens_a_decision(queue, corpus):
    _call("rebuild_proposals")
    pending = _call("list_proposals", status=prop.STATUS_PENDING, kind=None)["proposals"]
    _call("decide_proposal", proposal_id=pending[0]["proposal_id"],
          body=offers_routes.Verdict(status=prop.STATUS_REJECTED, reviewer_note="covered"))

    again = _call("rebuild_proposals")
    assert again["queue"][prop.STATUS_PENDING] == 0
    assert again["queue"][prop.STATUS_REJECTED] == 1


# ── Listing and filtering ─────────────────────────────────────────────────────

def test_unknown_status_and_kind_are_refused(queue, corpus):
    with pytest.raises(HTTPException) as bad_status:
        _call("list_proposals", status="maybe", kind=None)
    assert bad_status.value.status_code == 422
    with pytest.raises(HTTPException) as bad_kind:
        _call("list_proposals", status=None, kind="sideways")
    assert bad_kind.value.status_code == 422


def test_a_revision_carries_the_text_it_would_replace(queue, corpus):
    proposal = prop.build_proposal(prop.KIND_REVISION, _fields(text=TEXT_MOSUL + " Extra."),
                                   ["<1@x>#1"], target_code="MO1")
    prop.save(proposal)
    shown = _call("get_proposal", proposal_id=proposal.proposal_id)
    assert shown["current_text"] == TEXT_MOSUL, "the reviewer sees both sides of the change"
    assert shown["proposed_text"].endswith("Extra.")


def test_missing_proposal_is_a_404(queue, corpus):
    with pytest.raises(HTTPException) as raised:
        _call("get_proposal", proposal_id="new-doesnotexist")
    assert raised.value.status_code == 404


# ── Verdicts ──────────────────────────────────────────────────────────────────

def test_approval_records_edits_and_becomes_terminal(queue, corpus):
    proposal = prop.build_proposal(prop.KIND_NEW, _fields(), ["<2@x>#1"])
    prop.save(proposal)
    decided = _call("decide_proposal", proposal_id=proposal.proposal_id,
                    body=offers_routes.Verdict(status=prop.STATUS_APPROVED,
                                               reviewer_note="named it",
                                               edited_fields={"code": "MARSH"}))
    assert decided["status"] == prop.STATUS_APPROVED
    assert decided["fields"]["code"] == "MARSH"
    assert decided["fields"]["active"] is False, "approval never activates a row"
    assert decided["decided_at"]


def test_deciding_twice_is_a_conflict_not_a_silent_overwrite(queue, corpus):
    proposal = prop.build_proposal(prop.KIND_NEW, _fields(), ["<2@x>#1"])
    prop.save(proposal)
    _call("decide_proposal", proposal_id=proposal.proposal_id,
          body=offers_routes.Verdict(status=prop.STATUS_APPROVED))
    with pytest.raises(HTTPException) as raised:
        _call("decide_proposal", proposal_id=proposal.proposal_id,
              body=offers_routes.Verdict(status=prop.STATUS_REJECTED))
    assert raised.value.status_code == 409


def test_editing_a_field_outside_the_catalogue_schema_is_a_conflict(queue, corpus):
    proposal = prop.build_proposal(prop.KIND_NEW, _fields(), ["<2@x>#1"])
    prop.save(proposal)
    with pytest.raises(HTTPException) as raised:
        _call("decide_proposal", proposal_id=proposal.proposal_id,
              body=offers_routes.Verdict(status=prop.STATUS_APPROVED,
                                         edited_fields={"sneaky": "x"}))
    assert raised.value.status_code == 409


# ── Evidence ──────────────────────────────────────────────────────────────────

def test_evidence_returns_the_sent_day_a_proposal_cites(corpus):
    evidence = _call("get_evidence_day", day_key="<1@x>#1")
    assert evidence["overnight_city"] == "Mosul"
    assert evidence["attachment_name"] == "offer.docx"
    assert "Al-Nuri" in evidence["text"]


def test_unknown_evidence_key_is_a_404(corpus):
    with pytest.raises(HTTPException) as raised:
        _call("get_evidence_day", day_key="<nope@x>#9")
    assert raised.value.status_code == 404


# ── Catalogue listing ─────────────────────────────────────────────────────────

def test_catalogue_listing_reports_each_template(monkeypatch):
    monkeypatch.setattr(offers_routes, "load_templates", lambda: {
        "MO1": {"title": "Mosul old city", "overnight_city": "Mosul",
                "region": "Northern Iraq", "active": True, "needs_review": False,
                "full_text": TEXT_MOSUL},
    })
    listing = _call("list_catalogue")
    assert listing["count"] == 1
    assert listing["templates"][0]["code"] == "MO1"
    assert listing["templates"][0]["words"] == len(TEXT_MOSUL.split())


# ── What a reviewer is shown ──────────────────────────────────────────────────

def test_a_revision_diff_marks_only_what_changed():
    """
    A reviewer reads a revision by its deviation. Most revisions differ by one
    clause inside otherwise identical prose, so showing both sides in full hides
    the change instead of showing it.
    """
    diff = offers_routes._word_diff("visit the ziggurat and return",
                                    "visit the great ziggurat and return")
    assert ("added", "great") in diff
    assert [words for op, words in diff if op == "removed"] == []
    assert " ".join(w for op, w in diff if op != "removed") == "visit the great ziggurat and return"


def test_a_diff_reports_a_removal_as_well_as_an_addition():
    diff = offers_routes._word_diff("drive south to the marshes at dawn",
                                    "drive to the marshes")
    assert ("removed", "south") in diff
    assert ("removed", "at dawn") in diff


def test_identical_texts_produce_no_change():
    diff = offers_routes._word_diff(TEXT_MOSUL, TEXT_MOSUL)
    assert {op for op, _ in diff} == {"same"}


def test_a_new_template_has_nothing_to_diff_against(queue, corpus):
    """A new template replaces no text, so there is no before side to compare."""
    _call("rebuild_proposals")
    listed = _call("list_proposals", status=prop.STATUS_PENDING, kind=None)["proposals"][0]
    assert listed["kind"] == prop.KIND_NEW
    assert listed["diff"] == []
    assert listed["current_text"] is None


def test_a_revision_carries_its_diff_and_both_evidence_numbers(queue, corpus):
    proposal = prop.build_proposal(prop.KIND_REVISION,
                                   _fields(text=TEXT_MOSUL + " Then coffee by the river."),
                                   ["<1@x>#1"], target_code="MO1", occurrences=3, weight=1.4)
    prop.save(proposal)
    shown = _call("get_proposal", proposal_id=proposal.proposal_id)
    assert ("added", "Then coffee by the river.") in [(op, w) for op, w in shown["diff"]]
    assert shown["occurrences"] == 3 and shown["weight"] == 1.4


def test_a_proposal_shows_the_mirror_template_it_may_reverse(queue, corpus):
    proposal = prop.build_proposal(prop.KIND_NEW, _fields(), ["<2@x>#1"],
                                   reordered_codes=["URUKNA"])
    prop.save(proposal)
    shown = _call("get_proposal", proposal_id=proposal.proposal_id)
    assert shown["reordered_codes"] == ["URUKNA"]


# ── Applying to the catalogue ─────────────────────────────────────────────────

class _FakeApply:
    """Records how apply_approved was called, and what it was told to do."""

    def __init__(self):
        self.calls = []

    def __call__(self, sheet_id, dry_run=True, service=None, only=None):
        self.calls.append({"sheet_id": sheet_id, "dry_run": dry_run, "only": only})
        return {"appends": [{"proposal_id": "new-1", "code": "MO2", "row": []}],
                "updates": [], "skipped": [], "dry_run": dry_run,
                "written": 0 if dry_run else 1, "verified": 0 if dry_run else 1}


def _patch_apply(monkeypatch):
    from services.offers import apply_to_sheet
    fake = _FakeApply()
    monkeypatch.setattr(apply_to_sheet, "apply_approved", fake)
    return fake


def test_apply_plans_and_writes_nothing_by_default(monkeypatch):
    """A write to the catalogue must be asked for in words."""
    fake = _patch_apply(monkeypatch)
    from routes.offers.offers_routes import ApplyRequest
    plan = _call("apply_to_catalogue", body=ApplyRequest())
    assert plan["dry_run"] is True
    assert [c["dry_run"] for c in fake.calls] == [True]


def test_apply_plans_again_before_it_writes(monkeypatch):
    """
    The first plan is what a person read. The second runs against the sheet as
    it is at the moment of writing, so a row someone else added in between is
    not overwritten.
    """
    fake = _patch_apply(monkeypatch)
    from routes.offers.offers_routes import ApplyRequest
    result = _call("apply_to_catalogue", body=ApplyRequest(write=True))
    assert [c["dry_run"] for c in fake.calls] == [True, False]
    assert result["written"] == 1


def test_apply_never_takes_the_sheet_id_from_the_request(monkeypatch):
    from services.itinerary.pipeline import config
    fake = _patch_apply(monkeypatch)
    from routes.offers.offers_routes import ApplyRequest
    _call("apply_to_catalogue", body=ApplyRequest(write=True))
    assert {c["sheet_id"] for c in fake.calls} == {config.JSON_DB_SHEET_ID}


def test_apply_with_an_empty_plan_does_not_write(monkeypatch):
    from services.offers import apply_to_sheet
    calls = []

    def empty(sheet_id, dry_run=True, service=None, only=None):
        calls.append(dry_run)
        return {"appends": [], "updates": [], "skipped": [], "dry_run": dry_run,
                "written": 0, "verified": 0}

    monkeypatch.setattr(apply_to_sheet, "apply_approved", empty)
    from routes.offers.offers_routes import ApplyRequest
    _call("apply_to_catalogue", body=ApplyRequest(write=True))
    assert calls == [True], "an empty plan must not reach the sheet"


def test_apply_reports_a_refusal_rather_than_failing_silently(monkeypatch):
    from services.offers import apply_to_sheet

    def refuse(sheet_id, dry_run=True, service=None, only=None):
        raise RuntimeError("merged cells in the target range")

    monkeypatch.setattr(apply_to_sheet, "apply_approved", refuse)
    from routes.offers.offers_routes import ApplyRequest
    with pytest.raises(HTTPException) as caught:
        _call("apply_to_catalogue", body=ApplyRequest())
    assert caught.value.status_code == 502
    assert "merged cells" in caught.value.detail


# ── Suggesting the missing fields ─────────────────────────────────────────────

def _suggest_returns(monkeypatch, answer=None, error=None):
    from services.offers import suggest_row

    async def fake(day_text, overnight_city="", owner=None):
        if error:
            raise suggest_row.SuggestionError(error)
        return answer or {"title": "Old Mosul", "city": "Mosul",
                          "included_sites": [], "pricing_tags": ["guide_day"],
                          "cleaned_text": day_text, "confidence": {},
                          "dropped_sites": [], "model": "test-model",
                          "endpoint": "http://x/v1", "suggested_at": "2026-09-05T00:00:00+00:00"}

    monkeypatch.setattr(suggest_row, "suggest_catalogue_row", fake)


def test_a_suggestion_is_stored_and_returned_without_touching_the_fields(
        queue, corpus, monkeypatch):
    _suggest_returns(monkeypatch)
    _call("rebuild_proposals")
    pending = _call("list_proposals", status=prop.STATUS_PENDING, kind=None)["proposals"][0]
    before = dict(prop.load(pending["proposal_id"]).fields)

    shown = _call("suggest_row_for_proposal", proposal_id=pending["proposal_id"])
    assert shown["suggested"]["title"] == "Old Mosul"
    assert prop.load(pending["proposal_id"]).fields == before


def test_a_model_that_does_not_answer_is_a_502_and_leaves_the_card_usable(
        queue, corpus, monkeypatch):
    _suggest_returns(monkeypatch, error="the model did not answer: timed out")
    _call("rebuild_proposals")
    pending = _call("list_proposals", status=prop.STATUS_PENDING, kind=None)["proposals"][0]
    with pytest.raises(HTTPException) as raised:
        _call("suggest_row_for_proposal", proposal_id=pending["proposal_id"])
    assert raised.value.status_code == 502
    assert prop.load(pending["proposal_id"]).suggested is None


def test_suggesting_on_a_missing_proposal_is_a_404(queue, corpus, monkeypatch):
    _suggest_returns(monkeypatch)
    with pytest.raises(HTTPException) as raised:
        _call("suggest_row_for_proposal", proposal_id="new-nothing")
    assert raised.value.status_code == 404


def test_suggesting_on_a_decided_proposal_is_a_409(queue, corpus, monkeypatch):
    _suggest_returns(monkeypatch)
    _call("rebuild_proposals")
    pending = _call("list_proposals", status=prop.STATUS_PENDING, kind=None)["proposals"][0]
    _call("decide_proposal", proposal_id=pending["proposal_id"],
          body=offers_routes.Verdict(status=prop.STATUS_REJECTED))
    with pytest.raises(HTTPException) as raised:
        _call("suggest_row_for_proposal", proposal_id=pending["proposal_id"])
    assert raised.value.status_code == 409


def test_the_reviewer_can_carry_the_suggested_columns_into_a_verdict(queue, corpus):
    """
    The page has no input for title, city, sites or tags. Accepting holds them
    on the card and the verdict carries them, so what is approved is what can
    later be applied.
    """
    _call("rebuild_proposals")
    pending = _call("list_proposals", status=prop.STATUS_PENDING, kind=None)["proposals"][0]
    decided = _call("decide_proposal", proposal_id=pending["proposal_id"],
                    body=offers_routes.Verdict(
                        status=prop.STATUS_APPROVED,
                        edited_fields={"code": "MO2", "title": "Old Mosul",
                                       "city": "Mosul",
                                       "included_sites_json": '["MO_NM"]',
                                       "pricing_tags_json": '["guide_day"]'}))
    stored = prop.load(decided["proposal_id"]).fields
    assert stored["title"] == "Old Mosul"
    assert stored["included_sites_json"] == '["MO_NM"]'
