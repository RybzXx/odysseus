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
    from services.offers import gap_report
    monkeypatch.setattr(prop, "TEMPLATE_PROPOSAL_DIR", str(tmp_path / "proposals"))
    monkeypatch.setattr(gap_report, "GAP_SUMMARY_FILE", str(tmp_path / "catalogue_gap.json"))
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
