"""
tests/test_sequence_grade.py

Tests for WP10's grader: a proposed day-code sequence marked against the offer
that was actually sent.

The defect these guard against is a grade that flatters. A proposal scored
against a second proposal says only that two answers differ. Scored against the
sent offer it says which one was right, and a grader that quietly forgives a
wrong night removes the only reason to run it.

Per tests/TESTING_STANDARD.md: no network, no mail, and no model.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary.sequence_grade import (  # noqa: E402
    POSITION_DIFFER,
    POSITION_ONLY_PROPOSED,
    POSITION_ONLY_SENT,
    POSITION_SAME,
    POSITION_UNKNOWN,
    format_grade,
    grade_sequence,
)
from services.offers.models import OfferDay, SentOffer  # noqa: E402

# Codes carry an overnight city; a day trip and a departure carry none.
TEMPLATES = {
    "ARRBG": {"overnight_city": "Baghdad"},
    "BG1": {"overnight_city": "Baghdad"},
    "KA": {"overnight_city": "Karbala"},
    "NA1": {"overnight_city": "Nasiriyah"},
    "MO1": {"overnight_city": "Mosul"},
    "SUEBDEP": {"overnight_city": ""},          # a departure day
    "SULAY": {"overnight_city": "Sulaymaniya"},  # the catalogue's own spelling
}


def _offer(*cities, message_id="<a@bilweekend.iq>"):
    return SentOffer(
        message_id=message_id, subject="Re: Iraq trip",
        sent_at=datetime(2026, 2, 4, tzinfo=timezone.utc),
        attachment_name="trip.pdf",
        days=[OfferDay(day_number=n + 1, text=f"Day {n + 1}", overnight_city=city)
              for n, city in enumerate(cities)],
    )


# ── a right answer scores full marks ─────────────────────────────────────────

def test_a_sequence_that_matches_the_offer_scores_every_night():
    grade = grade_sequence(["ARRBG", "KA", "MO1"], TEMPLATES,
                           _offer("Baghdad", "Karbala", "Mosul"), source="rules")
    assert grade.matched == 3
    assert grade.nights_sent == 3
    assert grade.share == 1.0
    assert grade.day_count_agrees is True
    assert [p.verdict for p in grade.positions] == [POSITION_SAME] * 3


def test_the_statement_carries_its_own_count_and_denominator():
    grade = grade_sequence(["ARRBG", "KA"], TEMPLATES,
                           _offer("Baghdad", "Mosul"), source="model")
    assert "1 of 2" in grade.statement
    assert "model" in grade.statement


# ── a wrong night is named, not forgiven ─────────────────────────────────────

def test_a_wrong_city_is_named_at_its_own_night():
    grade = grade_sequence(["ARRBG", "KA", "MO1"], TEMPLATES,
                           _offer("Baghdad", "Nasiriyah", "Mosul"))
    assert grade.matched == 2
    wrong = grade.positions[1]
    assert wrong.verdict == POSITION_DIFFER
    assert wrong.night == 2
    assert wrong.proposed_city == "Karbala"
    assert wrong.sent_city == "Nasiriyah"


def test_a_proposal_that_runs_long_is_marked_at_the_extra_nights():
    grade = grade_sequence(["ARRBG", "KA", "MO1"], TEMPLATES,
                           _offer("Baghdad", "Karbala"))
    assert grade.matched == 2
    assert grade.positions[2].verdict == POSITION_ONLY_PROPOSED
    assert grade.day_count_agrees is False


def test_a_proposal_that_runs_short_is_marked_at_the_missing_nights():
    grade = grade_sequence(["ARRBG"], TEMPLATES,
                           _offer("Baghdad", "Karbala", "Mosul"))
    assert grade.matched == 1
    assert [p.verdict for p in grade.positions[1:]] == [POSITION_ONLY_SENT] * 2
    assert grade.positions[2].sent_city == "Mosul"
    assert grade.share == pytest.approx(1 / 3)


# ── what is not a night does not take a position ─────────────────────────────

def test_a_departure_day_is_not_a_night():
    """A code with no overnight city ends the trip. It cannot be in a wrong city."""
    grade = grade_sequence(["ARRBG", "KA", "SUEBDEP"], TEMPLATES,
                           _offer("Baghdad", "Karbala"))
    assert grade.nights_proposed == 2
    assert grade.matched == 2
    assert grade.day_count_agrees is True


# ── spelling must not read as a different night ──────────────────────────────

def test_two_spellings_of_one_city_are_one_night():
    """The corpus holds 38 overnight strings for about a dozen places."""
    grade = grade_sequence(["SULAY"], TEMPLATES, _offer("Sulaymaniyah"))
    assert grade.matched == 1


def test_a_city_with_a_note_still_matches():
    grade = grade_sequence(["ARRBG"], TEMPLATES, _offer("Baghdad (Not Included)"))
    assert grade.matched == 1


# ── a missing template is the catalogue's fault, not the proposer's ──────────

def test_a_code_outside_the_catalogue_is_named_and_not_scored_as_a_miss():
    grade = grade_sequence(["ARRBG", "NOPE"], TEMPLATES, _offer("Baghdad"))
    assert grade.unknown_codes == ["NOPE"]
    assert grade.matched == 1
    assert grade.nights_sent == 1
    assert any(p.verdict == POSITION_UNKNOWN for p in grade.positions)


# ── boundaries ───────────────────────────────────────────────────────────────

def test_an_empty_proposal_scores_nothing_and_names_every_night_it_missed():
    grade = grade_sequence([], TEMPLATES, _offer("Baghdad", "Karbala"))
    assert grade.matched == 0
    assert grade.share == 0.0
    assert len(grade.positions) == 2


def test_an_offer_with_no_named_night_gives_a_share_of_zero_and_does_not_divide():
    grade = grade_sequence(["ARRBG"], TEMPLATES, _offer())
    assert grade.nights_sent == 0
    assert grade.share == 0.0
    assert grade.positions[0].verdict == POSITION_ONLY_PROPOSED


def test_a_day_trip_in_the_offer_is_not_a_night():
    """An offer day with no overnight city is a day trip, not a night."""
    grade = grade_sequence(["ARRBG", "KA"], TEMPLATES,
                           _offer("Baghdad", "", "Karbala"))
    assert grade.nights_sent == 2
    assert grade.matched == 2


def test_the_grade_never_changes_the_offer():
    offer = _offer("Baghdad", "Karbala")
    before = [(d.day_number, d.overnight_city) for d in offer.days]
    grade_sequence(["ARRBG", "MO1"], TEMPLATES, offer)
    assert [(d.day_number, d.overnight_city) for d in offer.days] == before


# ── a graded draft is a record, not work on the desk ─────────────────────────

@pytest.fixture
def draft_store(tmp_path, monkeypatch):
    from services.itinerary import drafts

    monkeypatch.setattr(drafts, "ITINERARY_DRAFT_DIR",
                        str(tmp_path / "itinerary_drafts"))


def test_a_graded_draft_never_reaches_the_desk_s_request_list(draft_store):
    """47 sold trips must not appear as work waiting to be done."""
    from services.itinerary.drafts import (
        OPEN_REQUEST_ORIGINS, ORIGIN_GRADED, iter_drafts, open_draft)
    from services.itinerary.sequence_grade import open_graded_draft

    open_draft({"name": "a live request"}, request_id="curated:1")
    open_graded_draft(_offer("Baghdad", message_id="<g@bilweekend.iq>"))

    assert len(list(iter_drafts())) == 2
    open_requests = list(iter_drafts(OPEN_REQUEST_ORIGINS))
    assert len(open_requests) == 1
    assert all(d.origin != ORIGIN_GRADED for d in open_requests)


def test_grading_one_offer_twice_stays_on_one_thread(draft_store):
    from services.itinerary.sequence_grade import open_graded_draft

    offer = _offer("Baghdad", "Karbala", message_id="<h@bilweekend.iq>")
    assert open_graded_draft(offer).draft_id == open_graded_draft(offer).draft_id


def test_a_recorded_read_keeps_its_grade_and_says_which_read_it_was(draft_store):
    from services.itinerary.sequence_grade import READ_ONE, READ_TWO, record_read

    offer = _offer("Baghdad", "Karbala", message_id="<i@bilweekend.iq>")
    draft, first = record_read(offer, ["ARRBG", "MO1"], TEMPLATES, READ_ONE)
    draft, second = record_read(offer, ["ARRBG", "KA"], TEMPLATES, READ_TWO)

    assert first.matched == 1
    assert second.matched == 2
    assert len(draft.sequences) == 2
    assert [s.in_reply_to for s in draft.sequences] == [READ_ONE, READ_TWO]
    assert "1 of 2" in draft.sequences[0].note
    assert "2 of 2" in draft.sequences[1].note


def test_an_unknown_read_is_refused(draft_store):
    from services.itinerary.sequence_grade import record_read

    with pytest.raises(ValueError):
        record_read(_offer("Baghdad"), ["ARRBG"], TEMPLATES, "read three")


def test_a_correction_on_a_graded_draft_reaches_the_rule_queue(draft_store):
    """10.6: the human's reason is a comment, and WP4b reads comments."""
    from services.itinerary.drafts import RULE_STATE_NEW, add_comment, iter_comments
    from services.itinerary.sequence_grade import READ_ONE, record_read

    offer = _offer("Baghdad", "Nasiriyah", message_id="<j@bilweekend.iq>")
    draft, _ = record_read(offer, ["ARRBG", "BG1"], TEMPLATES, READ_ONE)
    add_comment(draft.draft_id, "night two goes south when the client asks for Ur")

    queued = list(iter_comments(RULE_STATE_NEW))
    assert len(queued) == 1
    assert queued[0]["draft_id"] == draft.draft_id
    assert "goes south" in queued[0]["text"]


def test_the_formatted_grade_names_every_wrong_night():
    grade = grade_sequence(["ARRBG", "KA"], TEMPLATES,
                           _offer("Baghdad", "Mosul"), source="model")
    text = format_grade(grade)
    assert "1 of 2" in text
    assert "differ" in text
    assert "Mosul" in text
