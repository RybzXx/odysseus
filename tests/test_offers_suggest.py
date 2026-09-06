"""
tests/test_offers_suggest.py

Tests for the model that completes the catalogue columns a draft leaves empty.

The model proposes and never decides. Its answer is machine text until the
reviewer accepts it, and nothing here may merge a suggestion into a proposal's
fields.

No test reaches the network. The model layer is replaced in every case, so the
suite says nothing about whether the configured endpoint answers well — only
about what this code does with an answer.
"""
import json
import sys
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.offers import proposals as prop  # noqa: E402
from services.offers.catalogue import TEMPLATE_FIELDS  # noqa: E402
from services.offers.suggest_row import (  # noqa: E402
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    SuggestionError,
    build_prompt,
    known_site_codes,
    parse_answer,
    pricing_tags_for,
)

DAY = ("8 AM Start the day with discovering the reconstruction of the old city, "
       "especially Al-Nuri Mosque and Al Hadbaa Minaret.")


def _fields(text=DAY, overnight="Mosul"):
    base = {name: "" for name in TEMPLATE_FIELDS}
    base.update(code="", full_text=text, overnight_city=overnight,
                included_sites_json="[]", pricing_tags_json="[]",
                active=False, needs_review=True)
    return base


def _answer(**over):
    body = {"title": "Old Mosul", "city": "Mosul",
            "included_sites": [], "cleaned_text": DAY,
            "confidence": {"title": "high", "city": "high", "included_sites": "high"}}
    body.update(over)
    return json.dumps(body)


# --- the pricing rule -------------------------------------------------------

def test_the_pricing_rule_reproduces_every_catalogue_row():
    """
    The rule exists so a model is never asked for it. If it disagrees with canon
    on one row, the rule is wrong and the model should have been asked.
    """
    from services.offers import load_templates
    for code, row in load_templates().items():
        expected = sorted(row.get("pricing_tags") or [])
        actual = sorted(pricing_tags_for(row.get("overnight_city") or ""))
        assert actual == expected, f"{code}: rule says {actual}, canon says {expected}"


def test_a_day_with_no_overnight_city_carries_no_hotel_night():
    assert "hotel_night" not in pricing_tags_for("")
    assert "hotel_night" in pricing_tags_for("Erbil")


# --- the closed vocabularies ------------------------------------------------

def test_the_site_vocabulary_is_read_from_the_pricing_data():
    sites = known_site_codes()
    assert len(sites) > 50
    assert "BG_OLD_CITY" in sites
    assert sites["BG_OLD_CITY"]["city"] == "Baghdad"


def test_the_prompt_carries_the_site_codes_and_the_regions():
    system = build_prompt(DAY, "Mosul")[0]["content"]
    assert "BG_OLD_CITY" in system
    assert "Central Iraq" in system
    assert "Never invent a site code" in system


def test_the_prompt_carries_the_day_and_its_overnight_city():
    user = build_prompt(DAY, "Mosul")[1]["content"]
    assert DAY in user
    assert "Mosul" in user


# --- reading the answer -----------------------------------------------------

def test_an_invented_site_code_is_dropped_and_named():
    """A silent invention would reach the catalogue. A named one does not."""
    parsed = parse_answer(_answer(included_sites=["BG_OLD_CITY", "NOT_A_SITE"]), DAY, "Mosul")
    assert parsed["included_sites"] == ["BG_OLD_CITY"]
    assert parsed["dropped_sites"] == ["NOT_A_SITE"]


def test_pricing_tags_never_come_from_the_model():
    parsed = parse_answer(_answer(pricing_tags=["nonsense"]), DAY, "Mosul")
    assert parsed["pricing_tags"] == ["guide_day", "transport_day", "hotel_night"]


def test_an_unsure_field_is_marked_low_and_still_answered():
    parsed = parse_answer(
        _answer(title="A guess", confidence={"title": "low", "city": "high",
                                             "included_sites": "high"}), DAY, "Mosul")
    assert parsed["title"] == "A guess"
    assert parsed["confidence"]["title"] == CONFIDENCE_LOW
    assert parsed["confidence"]["city"] == CONFIDENCE_HIGH


def test_a_missing_confidence_reads_as_high_rather_than_absent():
    parsed = parse_answer(json.dumps({"title": "X", "city": "Y"}), DAY, "Mosul")
    assert set(parsed["confidence"]) == {"title", "city", "included_sites"}


def test_an_empty_cleaned_text_falls_back_to_the_day_as_sent():
    """Losing the wording to a blank answer would be worse than not asking."""
    assert parse_answer(_answer(cleaned_text=""), DAY, "Mosul")["cleaned_text"] == DAY


def test_json_wrapped_in_prose_is_still_read():
    raw = "Here is the row:\n" + _answer() + "\nHope that helps."
    assert parse_answer(raw, DAY, "Mosul")["title"] == "Old Mosul"


def test_an_answer_that_is_not_json_is_a_model_failure():
    with pytest.raises(SuggestionError):
        parse_answer("I cannot help with that.", DAY, "Mosul")


def test_broken_json_is_a_model_failure():
    with pytest.raises(SuggestionError):
        parse_answer('{"title": "unterminated', DAY, "Mosul")


# --- storing it -------------------------------------------------------------

@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(prop, "TEMPLATE_PROPOSAL_DIR", str(tmp_path / "proposals"))
    return tmp_path


def _saved(fields=None):
    proposal = prop.build_proposal(prop.KIND_NEW, fields or _fields(), ["<1@x>#1"])
    prop.save(proposal)
    return proposal


def test_a_suggestion_never_touches_the_drafted_fields(queue):
    proposal = _saved()
    before = dict(proposal.fields)
    prop.record_suggestion(proposal.proposal_id, {"title": "Old Mosul"})
    assert prop.load(proposal.proposal_id).fields == before


def test_a_suggestion_round_trips(queue):
    proposal = _saved()
    prop.record_suggestion(proposal.proposal_id,
                           {"title": "Old Mosul", "model": "gemma4:31b-cloud"})
    stored = prop.load(proposal.proposal_id).suggested
    assert stored["title"] == "Old Mosul"
    assert stored["model"] == "gemma4:31b-cloud"


def test_a_second_suggestion_replaces_the_first(queue):
    proposal = _saved()
    prop.record_suggestion(proposal.proposal_id, {"title": "First"})
    prop.record_suggestion(proposal.proposal_id, {"title": "Second"})
    assert prop.load(proposal.proposal_id).suggested["title"] == "Second"


def test_a_rebuild_does_not_erase_a_suggestion(queue):
    """
    A rebuild redraws every proposal. The reviewer works through hundreds of
    cards across sittings, and a rebuild in between must not undo that.
    """
    proposal = _saved()
    prop.record_suggestion(proposal.proposal_id, {"title": "Old Mosul"})
    prop.save(prop.build_proposal(prop.KIND_NEW, _fields(), ["<1@x>#1"]))
    assert prop.load(proposal.proposal_id).suggested["title"] == "Old Mosul"


def test_a_fresh_suggestion_overwrites_the_kept_one(queue):
    proposal = _saved()
    prop.record_suggestion(proposal.proposal_id, {"title": "Old"})
    replacement = prop.build_proposal(prop.KIND_NEW, _fields(), ["<1@x>#1"])
    replacement.suggested = {"title": "New"}
    prop.save(replacement)
    assert prop.load(proposal.proposal_id).suggested["title"] == "New"


def test_suggesting_on_a_decided_proposal_is_refused(queue):
    proposal = _saved()
    prop.record_verdict(proposal.proposal_id, prop.STATUS_REJECTED)
    with pytest.raises(prop.ProposalError):
        prop.record_suggestion(proposal.proposal_id, {"title": "too late"})


def test_suggesting_on_a_missing_proposal_is_refused(queue):
    with pytest.raises(prop.ProposalError):
        prop.record_suggestion("new-nothing", {"title": "x"})


# --- the gate ---------------------------------------------------------------

def test_canon_carries_no_formatting_fault_for_a_cleaner_to_fix():
    """
    The gate on the cleaner rests on this. Canon is clean, so a correct cleaner
    returns all 28 rows unchanged. If canon gains a real fault, the gate has to
    count that row as a pass when the change is the fix.
    """
    import re
    from services.offers import load_templates
    for code, row in load_templates().items():
        text = row.get("full_text") or ""
        assert text == text.strip(), code
        assert "  " not in text, code
        assert "\r" not in text, code
        assert "\n\n\n" not in text, code
        assert not re.search(r"[ \t]+\n", text), code
        assert not re.search(r"\s[,.;:]", text), code


def test_an_hour_at_the_head_of_a_day_survives_the_cleaner():
    """
    The date rule once made every part optional, so its trailing year matched a
    bare number on its own. "7 AM Start the day" became "AM Start the day", and
    MaMEB reached the sheet on 2026-09-06 with its hour gone.

    A number at the head of a day is a start time far more often than a year.
    """
    from services.offers.catalogue import as_catalogue_text
    assert as_catalogue_text("7 AM Start the day.") == "7 AM Start the day."
    assert as_catalogue_text("8 AM After breakfast we go.") == "8 AM After breakfast we go."
    assert as_catalogue_text("2026 was a good year.") == "2026 was a good year."


@pytest.mark.parametrize("sent, wanted", [
    ("Monday, 5 April 2026, Visit Babylon.", "Visit Babylon."),
    ("5 April 2026 Visit Babylon.", "Visit Babylon."),
    ("April 5, 2026 Visit Babylon.", "Visit Babylon."),
    ("Tuesday Visit Babylon.", "Visit Babylon."),
])
def test_a_real_date_is_still_stripped(sent, wanted):
    """The rule narrowed to protect the hour. It must still do its own job."""
    from services.offers.catalogue import as_catalogue_text
    assert as_catalogue_text(sent) == wanted


def test_a_space_before_a_mark_is_closed_up():
    """
    ArrSU carried "Monastery ," and KANJ carried "rest ." and "check -in". All
    three came from the sent offers, where a line was edited and the space
    stayed. Removing one changes no word, so it belongs to form.
    """
    from services.offers.catalogue import as_catalogue_text
    assert as_catalogue_text("Visit the Monastery , and rest .") == "Visit the Monastery, and rest."
    assert as_catalogue_text("We check -in to the hotel.") == "We check-in to the hotel."


def test_the_cleaned_wording_is_withheld_while_the_gate_fails():
    """
    Spec 4.1 gates the cleaner on a round trip through canon. Measured on
    2026-09-05 with gemma4:31b-cloud: 11 of 28 unchanged. Until that passes the
    card shows the day as sent, whatever the model returned.
    """
    from services.offers import suggest_row
    assert suggest_row.CLEANING_ENABLED is False
    parsed = parse_answer(_answer(cleaned_text="A completely rewritten day."), DAY, "Mosul")
    assert parsed["cleaned_text"] == DAY


def test_the_fields_still_arrive_while_the_wording_is_withheld():
    """The two halves ship apart, so a failing cleaner costs no fields."""
    parsed = parse_answer(_answer(cleaned_text="rewritten"), DAY, "Mosul")
    assert parsed["title"] == "Old Mosul"
    assert parsed["city"] == "Mosul"


# --- catalogue wording ------------------------------------------------------

def test_a_catalogue_row_carries_no_date_and_no_overnight_trailer():
    """
    A sent day names the date it was sent for and the night it ended on. A
    catalogue row is used again on other dates, and its overnight city lives in
    its own column.
    """
    from services.offers.catalogue import as_catalogue_text
    sent = ("Tuesday Oct 7\n"
            "Morning departure to visit Shanidar Cave.\n"
            "Continue to Korek Mountain. Overnight: Korek Mountain / night 3.")
    assert as_catalogue_text(sent) == (
        "Morning departure to visit Shanidar Cave.\n"
        "Continue to Korek Mountain.")


def test_a_note_beside_the_date_is_kept():
    """
    The date is stripped as a prefix, not by dropping the line. "(Lunch OR
    Dinner is included)" sat beside a date on two offers, and it is content.
    """
    from services.offers.catalogue import as_catalogue_text
    out = as_catalogue_text("Wednesday, 30 September (Lunch is included)\nHead to Najaf.")
    assert "Lunch is included" in out
    assert "September" not in out


def test_one_sentence_sits_on_one_line():
    from services.offers.catalogue import as_catalogue_text
    out = as_catalogue_text("Visit the museum. Then walk the bazaar. Return at dusk.")
    assert out.splitlines() == ["Visit the museum.", "Then walk the bazaar.",
                                "Return at dusk."]


def test_an_abbreviation_does_not_start_a_new_line():
    """"Erbil Intl. Airport" and "approx. 1.5 hours" were being cut in half."""
    from services.offers.catalogue import as_catalogue_text
    assert as_catalogue_text("Transfer to Erbil Intl. Airport.") == \
        "Transfer to Erbil Intl. Airport."
    assert as_catalogue_text("Drive to Ur (approx. 1.5 hours).") == \
        "Drive to Ur (approx. 1.5 hours)."


def test_approving_turns_the_wording_into_a_catalogue_row(queue):
    """
    The verdict is the moment the text stops being a question about the corpus
    and becomes an answer for the catalogue.
    """
    proposal = prop.build_proposal(
        prop.KIND_NEW,
        _fields(text="Monday Mar 17\nArrival in Erbil. Overnight: Erbil / night 1."),
        ["<1@x>#1"])
    prop.save(proposal)
    decided = prop.record_verdict(proposal.proposal_id, prop.STATUS_APPROVED,
                                  edited_fields={"code": "ARREB"})
    assert decided.fields["full_text"] == "Arrival in Erbil."


def test_rejecting_leaves_the_wording_exactly_as_it_was_sent(queue):
    """A rejected row is evidence about the corpus, not a catalogue row."""
    sent = "Monday Mar 17\nArrival in Erbil. Overnight: Erbil / night 1."
    proposal = prop.build_proposal(prop.KIND_NEW, _fields(text=sent), ["<1@x>#1"])
    prop.save(proposal)
    decided = prop.record_verdict(proposal.proposal_id, prop.STATUS_REJECTED)
    assert decided.fields["full_text"] == sent


def test_approving_a_row_that_is_already_clean_changes_nothing(queue):
    clean = "Arrival in Erbil.\nExplore the citadel."
    proposal = prop.build_proposal(prop.KIND_NEW, _fields(text=clean), ["<1@x>#1"])
    prop.save(proposal)
    decided = prop.record_verdict(proposal.proposal_id, prop.STATUS_APPROVED,
                                  edited_fields={"code": "EB2"})
    assert decided.fields["full_text"] == clean
