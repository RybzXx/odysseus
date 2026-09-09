"""
tests/test_itinerary_desk.py

Tests for the itinerary desk: a request, two proposed day-code sequences, and
the conversation that revises one of them.

The model proposes and the rules propose. Neither decides, so these tests hold
the desk to showing both and to never letting a code the pipeline cannot build
reach a proposal.

Per tests/TESTING_STANDARD.md: no network, no sheet, no Google Docs. The model
layer and the pipeline are replaced in every case.
"""
import sys
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary import drafts  # noqa: E402
from services.itinerary.drafts import (  # noqa: E402
    SOURCE_MODEL,
    SOURCE_RULES,
    DraftError,
    ProposedSequence,
    add_comment,
    add_sequence,
    draft_id_for,
    load,
    open_draft,
    sequences_agree,
)
from services.itinerary.regions import (  # noqa: E402
    REGION_CENTRAL,
    REGION_KURDISTAN,
)
from services.itinerary.normalizer import normalize_from_dict  # noqa: E402
from services.itinerary.propose_sequence import ProposalError, parse_answer  # noqa: E402

# The live curated form's own keys. A sheet-header shape normalizes to the
# defaults instead, which is how a desk can quietly build a 5-day trip for an
# 8-day request. These tests hold the desk to the payload it really receives.
ROW = {
    "name": "Test Client", "numberOfPeople": "2", "tripDays": "8",
    "accommodation": "4 star",
    "regions": "kurdistan, central iraq",
    "travelDateMode": "range", "travelMonth": "April", "travelYear": "2026",
}

TEMPLATES = {"ARRBG": {}, "BG1": {}, "BBKA": {}, "NJ": {}}


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setattr(drafts, "ITINERARY_DRAFT_DIR", str(tmp_path / "itinerary_drafts"))
    return tmp_path


# --- reading a request ------------------------------------------------------

def test_a_request_row_normalises_to_the_generation_inputs():
    req = normalize_from_dict("k", ROW, source="curated")
    assert req.day_count == 8
    assert req.pax == 2
    assert req.hotel_tier == "4star"
    assert req.vehicle_type == "SMALL_CAR"
    assert set(req.requested_regions) == {REGION_KURDISTAN, REGION_CENTRAL}


def test_an_unmapped_region_is_warned_about_and_passed_through():
    """
    The vendored mapper keeps an unrecognised region rather than dropping it.
    It then matches no route, which is honest: the request said something the
    catalogue has no word for, and silence would hide that.
    """
    req = normalize_from_dict("k", {**ROW, "regions": "Atlantis"}, source="curated")
    assert req.requested_regions == ["Atlantis"]
    assert any("Atlantis" in w for w in req.parse_warnings)


# --- the thread -------------------------------------------------------------

def test_reopening_the_same_request_returns_the_same_thread(desk):
    first = open_draft(ROW)
    add_comment(first.draft_id, "end in Erbil")
    second = open_draft(dict(ROW))
    assert second.draft_id == first.draft_id
    assert len(second.comments) == 1, "re-opening must not start a second thread"


def test_a_draft_id_is_stable_for_one_request():
    assert draft_id_for(ROW) == draft_id_for(dict(ROW))
    assert draft_id_for(ROW) != draft_id_for({**ROW, "tripDays": "9"})


def test_a_thread_keeps_every_answer_with_the_comment_that_caused_it(desk):
    draft = open_draft(ROW)
    add_sequence(draft.draft_id, ProposedSequence(source=SOURCE_MODEL, day_codes=["ARRBG"]))
    add_comment(draft.draft_id, "add a Babylon day")
    add_sequence(draft.draft_id, ProposedSequence(
        source=SOURCE_MODEL, day_codes=["ARRBG", "BBKA"], in_reply_to="add a Babylon day"))
    stored = load(draft.draft_id)
    assert [s.day_codes for s in stored.sequences] == [["ARRBG"], ["ARRBG", "BBKA"]]
    assert stored.sequences[-1].in_reply_to == "add a Babylon day"


def test_a_comment_moves_the_model_answer_and_never_the_rules_answer(desk):
    """
    The rules are deterministic. A fixed second opinion across a whole thread is
    exactly what makes them worth running.
    """
    draft = open_draft(ROW)
    add_sequence(draft.draft_id, ProposedSequence(source=SOURCE_RULES, day_codes=["ARRBG", "BG1"]))
    for turn in ("one", "two", "three"):
        add_comment(draft.draft_id, turn)
        add_sequence(draft.draft_id, ProposedSequence(
            source=SOURCE_MODEL, day_codes=["NJ", turn], in_reply_to=turn))
    stored = load(draft.draft_id)
    assert stored.latest[SOURCE_RULES].day_codes == ["ARRBG", "BG1"]
    assert stored.latest[SOURCE_MODEL].day_codes == ["NJ", "three"]


def test_an_empty_comment_is_refused(desk):
    draft = open_draft(ROW)
    with pytest.raises(DraftError):
        add_comment(draft.draft_id, "   ")


def test_an_unknown_source_is_refused(desk):
    """A reader who cannot tell the two apart cannot judge a disagreement."""
    draft = open_draft(ROW)
    with pytest.raises(DraftError):
        add_sequence(draft.draft_id, ProposedSequence(source="somebody", day_codes=["NJ"]))


def test_a_draft_round_trips_across_a_reload(desk):
    draft = open_draft(ROW)
    add_sequence(draft.draft_id, ProposedSequence(source=SOURCE_MODEL, day_codes=["NJ"]))
    reread = load(draft.draft_id)
    assert reread.request_row == ROW
    assert reread.sequences[0].day_codes == ["NJ"]


# --- comparing the two ------------------------------------------------------

def test_two_identical_sequences_agree(desk):
    draft = open_draft(ROW)
    for source in (SOURCE_MODEL, SOURCE_RULES):
        add_sequence(draft.draft_id, ProposedSequence(source=source, day_codes=["ARRBG", "BG1"]))
    agreement = sequences_agree(load(draft.draft_id))
    assert agreement["same"] is True
    assert agreement["positions"] == ["same", "same"]


def test_a_difference_is_marked_position_by_position(desk):
    draft = open_draft(ROW)
    add_sequence(draft.draft_id, ProposedSequence(source=SOURCE_MODEL,
                                                  day_codes=["ARRBG", "NJ", "BBKA"]))
    add_sequence(draft.draft_id, ProposedSequence(source=SOURCE_RULES,
                                                  day_codes=["ARRBG", "BG1"]))
    agreement = sequences_agree(load(draft.draft_id))
    assert agreement["same"] is False
    assert agreement["positions"] == ["same", "differ", "only-model"]


def test_only_the_newest_answer_from_each_source_is_compared(desk):
    draft = open_draft(ROW)
    add_sequence(draft.draft_id, ProposedSequence(source=SOURCE_MODEL, day_codes=["NJ"]))
    add_sequence(draft.draft_id, ProposedSequence(source=SOURCE_MODEL, day_codes=["ARRBG"]))
    add_sequence(draft.draft_id, ProposedSequence(source=SOURCE_RULES, day_codes=["ARRBG"]))
    assert sequences_agree(load(draft.draft_id))["same"] is True


# --- reading the model's answer ---------------------------------------------

def test_a_code_outside_the_catalogue_is_dropped_and_named():
    """A code the pipeline cannot build must never reach a proposal."""
    kept, rejected, reason = parse_answer(
        '{"day_codes": ["ARRBG", "INVENTED", "BG1"], "reason": "a plan"}', TEMPLATES)
    assert kept == ["ARRBG", "BG1"]
    assert rejected == ["INVENTED"]
    assert reason == "a plan"


def test_json_wrapped_in_prose_is_still_read():
    kept, _, _ = parse_answer('Here you go:\n{"day_codes": ["NJ"]}\nGood luck.', TEMPLATES)
    assert kept == ["NJ"]


def test_an_answer_that_is_not_json_is_a_model_failure():
    with pytest.raises(ProposalError):
        parse_answer("I cannot plan that.", TEMPLATES)


def test_broken_json_is_a_model_failure():
    with pytest.raises(ProposalError):
        parse_answer('{"day_codes": ["NJ"', TEMPLATES)


def test_a_single_code_answered_as_a_string_is_still_read():
    kept, _, _ = parse_answer('{"day_codes": "NJ"}', TEMPLATES)
    assert kept == ["NJ"]


# --- the vocabulary ---------------------------------------------------------

def test_only_active_templates_may_be_proposed(monkeypatch):
    """
    An inactive row cannot be built, so a reviewer reading it would be reading
    an itinerary that cannot be generated.
    """
    from services.itinerary import propose_sequence
    from services.itinerary import generator
    monkeypatch.setattr(generator, "load_templates", lambda: {
        "LIVE": {"code": "LIVE", "active": True},
        "PENDING": {"code": "PENDING", "active": False},
    })
    assert set(propose_sequence.active_day_templates()) == {"LIVE"}


def test_a_template_field_reads_the_same_from_a_dict_and_an_object():
    """
    The pipeline hands out objects and the catalogue hands out dicts. A reader
    that knows one shape returns an empty overnight city for the other, and an
    empty overnight city binds no day at all, without saying so.
    """
    from services.itinerary.propose_sequence import field_of

    class Row:
        overnight_city = "Baghdad"
        region = None

    assert field_of({"overnight_city": "Baghdad"}, "overnight_city") == "Baghdad"
    assert field_of(Row(), "overnight_city") == "Baghdad"
    assert field_of(Row(), "region") == ""
    assert field_of({}, "active", True) is True


def test_the_prompt_carries_the_codes_and_the_request(monkeypatch):
    from services.itinerary import propose_sequence
    monkeypatch.setattr(propose_sequence, "_route_examples", lambda days, limit=4: [])
    messages = propose_sequence.build_prompt(
        normalize_from_dict("k", ROW, source="curated"),
        {"ARRBG": {"title": "Arrival", "city": "Baghdad",
                   "overnight_city": "Baghdad", "region": "Central Iraq"}})
    assert "ARRBG" in messages[0]["content"]
    assert "Never invent one" in messages[0]["content"]
    assert "Days: 8" in messages[1]["content"]
