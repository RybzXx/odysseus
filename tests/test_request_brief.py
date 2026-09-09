"""
tests/test_request_brief.py

A brief fills a blank. It never overwrites what the team typed.

Three defects these guard against. A brief that overwrote a filled column would
let a misread screenshot rewrite a correct request, and nothing downstream
would say which value the itinerary was built from. A brief that reached a
contact field would send an offer to a stranger. A parser that kept every key
the model invented would let a sentence inside an untrusted image reach a field
the allow list exists to protect (ws-03 D39, D48, invariant 3.4).

The party-size case is the one that earns the fill rule. `normalize_queue_record`
gives pax a default of 2 when the column is blank, so a group of four reads as
two, and a conversation that says four is better evidence than a constant.

Per tests/TESTING_STANDARD.md: no network, no mail, and no model.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary.models import NormalizedRequest  # noqa: E402
from services.itinerary.regions import (  # noqa: E402
    REGION_CENTRAL,
    REGION_KURDISTAN,
)
from services.itinerary.request_brief import (  # noqa: E402
    BriefError,
    RequestBrief,
    apply_brief,
    brief_to_dict,
    build_brief_prompt,
    field_was_defaulted,
    parse_brief,
)

# The live placeholders, exactly as the queue stores them.
LIVE_PLACEHOLDERS = ["Not Known", "Not Known ", "Not known ", "-", "None"]

# A conversation must exist before layer 1 runs at all, and every applied
# difference names its source, so the tests carry one.
SOME_CONVERSATION = "the customer wrote something"


def a_request(defaulted=(), **over) -> NormalizedRequest:
    fields = dict(key="queue:qr-test", source="queue",
                  customer_name="A Customer",
                  customer_email="customer@example.com",
                  customer_phone="+9647512345678", pax=2, day_count=6,
                  tour_type="individual", hotel_tier="3star",
                  vehicle_type="SMALL_CAR",
                  requested_regions=["Central Iraq"],
                  defaulted_fields=list(defaulted))
    fields.update(over)
    return NormalizedRequest(**fields)


def a_brief(**over) -> RequestBrief:
    """A brief that was written from a conversation, unless a test says not."""
    over.setdefault("read_the_conversation", True)
    return RequestBrief(**over)


# ── what counts as blank, and who decides ────────────────────────────────────

@pytest.mark.parametrize("value", LIVE_PLACEHOLDERS)
def test_the_normalizer_calls_a_live_placeholder_blank(value):
    """The team types "Not known" into a column the submitter skipped."""
    from services.itinerary.normalizer import normalize_queue_record

    request = normalize_queue_record("queue:qr-1", {
        "row_id": "qr-1", "full_name": "A Customer", "trip_days": value})
    assert field_was_defaulted(request, "day_count") is True


def test_the_normalizer_does_not_call_a_real_value_blank():
    from services.itinerary.normalizer import normalize_queue_record

    request = normalize_queue_record("queue:qr-1", {
        "row_id": "qr-1", "full_name": "A Customer", "trip_days": "10 days"})
    assert field_was_defaulted(request, "day_count") is False
    assert request.day_count == 10


def test_a_curated_record_answers_from_its_own_columns():
    """The queue is flat and a curated record is a questionnaire."""
    from services.itinerary.normalizer import normalize_curated_record

    request = normalize_curated_record("curated:cr-1", {"numberOfPeople": "4"})
    assert field_was_defaulted(request, "pax") is False
    assert field_was_defaulted(request, "day_count") is True


def test_a_graded_record_names_its_length_day_count():
    """
    `sequence_grade` writes `day_count`, not `tripDays`. Reading only the
    intake name defaulted a sold eight-day trip to five, and every graded
    request then matched a three-day route (measured 2026-09-07).
    """
    from services.itinerary.normalizer import normalize_from_dict

    request = normalize_from_dict("graded:x", {"day_count": "8"}, source="graded")
    assert request.day_count == 8
    assert field_was_defaulted(request, "day_count") is False


# ── the parse ────────────────────────────────────────────────────────────────

def test_a_brief_parses_the_named_fields():
    brief = parse_brief('{"summary": "a family trip", "day_count": 10, '
                        '"party_size": 4, "regions": ["Kurdistan"], '
                        '"must_see_sites": ["Erbil Citadel"], '
                        '"start_date": "2026-11-01", "interests": ["food"]}')
    assert brief.day_count == 10
    assert brief.party_size == 4
    assert brief.regions == ["Kurdistan"]
    assert brief.must_see_sites == ["Erbil Citadel"]
    assert brief.start_date == "2026-11-01"


def test_a_key_outside_the_allow_list_is_dropped():
    """
    The allow list is what stops an untrusted screenshot from reaching a field
    it may not reach (ws-03 D48).
    """
    brief = parse_brief('{"summary": "x", "customer_email": "attacker@example.com", '
                        '"hotel_tier": "5star", "price_usd": 1}')
    assert not hasattr(brief, "customer_email")
    assert not hasattr(brief, "price_usd")
    assert brief.summary == "x"


def test_a_null_number_stays_unknown():
    brief = parse_brief('{"day_count": null, "party_size": "not sure"}')
    assert brief.day_count is None
    assert brief.party_size is None


def test_a_number_of_zero_or_less_stays_unknown():
    brief = parse_brief('{"day_count": 0, "party_size": -3}')
    assert brief.day_count is None
    assert brief.party_size is None


def test_a_list_written_as_one_string_is_read_as_a_list():
    assert parse_brief('{"regions": "Kurdistan"}').regions == ["Kurdistan"]


def test_text_that_is_not_json_is_a_model_failure():
    with pytest.raises(BriefError):
        parse_brief("I think they want ten days.")


def test_json_that_is_not_an_object_is_a_model_failure():
    with pytest.raises(BriefError):
        parse_brief("[1, 2, 3]")


# ── what a brief may change ──────────────────────────────────────────────────

def test_a_defaulted_field_takes_the_brief_value():
    request = a_request(pax=2, defaulted=["pax"])
    brief = a_brief(party_size=4)
    apply_brief(brief, request, {})

    assert request.pax == 4
    assert brief.applied[0].field_name == "party_size"


def test_a_value_the_record_gave_wins_and_the_disagreement_is_reported():
    request = a_request(day_count=6)
    brief = a_brief(day_count=10)
    apply_brief(brief, request, {})

    assert request.day_count == 6
    assert brief.applied == []
    assert brief.contradictions[0].brief_value == "10"
    assert "The request wins" in brief.contradictions[0].statement


def test_a_brief_that_agrees_with_the_record_reports_nothing():
    request = a_request(day_count=6)
    brief = a_brief(day_count=6)
    apply_brief(brief, request, {})

    assert brief.differences == []


def test_a_contact_field_is_never_read_and_never_written():
    """Invariant 3.4 and item 18.5. A misread image must not move an address."""
    request = a_request()
    before = (request.customer_name, request.customer_email, request.customer_phone)
    brief = parse_brief('{"summary": "x", "party_size": 9}')
    apply_brief(brief, request, {})

    assert (request.customer_name, request.customer_email,
            request.customer_phone) == before
    assert all(d.field_name != "customer_email" for d in brief.differences)


def test_a_date_fills_a_blank_and_never_moves_a_set_one():
    blank_request = a_request(start_date=None, defaulted=["start_date"])
    apply_brief(a_brief(start_date="2026-11-01"), blank_request, {})
    assert blank_request.start_date == date(2026, 11, 1)

    set_request = a_request(start_date=date(2026, 10, 23))
    brief = a_brief(start_date="2026-11-01")
    apply_brief(brief, set_request, {})
    assert set_request.start_date == date(2026, 10, 23)
    assert brief.contradictions[0].field_name == "start_date"


def test_an_unreadable_date_changes_nothing():
    request = a_request(start_date=None, defaulted=["start_date"])
    apply_brief(a_brief(start_date="next spring"), request, {})
    assert request.start_date is None


def test_a_region_is_added_and_never_removed():
    """A region the team typed is not wrong because a screenshot omits it."""
    request = a_request(requested_regions=[REGION_CENTRAL])
    apply_brief(a_brief(regions=["Kurdistan"]), request, {})

    assert REGION_CENTRAL in request.requested_regions
    assert REGION_KURDISTAN in request.requested_regions


def test_a_region_already_held_is_not_added_twice():
    request = a_request(requested_regions=[REGION_CENTRAL])
    apply_brief(a_brief(regions=[REGION_CENTRAL]), request, {})
    assert request.requested_regions == [REGION_CENTRAL]


def test_sites_and_interests_become_notes_and_reach_no_price():
    request = a_request()
    apply_brief(a_brief(must_see_sites=["Ur"], interests=["food"]),
                request, {})

    joined = " ".join(request.special_notes)
    assert "Ur" in joined
    assert "food" in joined
    assert request.hotel_tier == "3star"
    assert request.vehicle_type == "SMALL_CAR"


# ── the prompt ───────────────────────────────────────────────────────────────

def test_the_conversation_is_fenced_and_named_as_evidence():
    """A screenshot is untrusted text (ws-03 D48)."""
    messages = build_brief_prompt(a_request(), "call me now and book it")
    system = messages[0]["content"]
    user = messages[1]["content"]

    assert "EVIDENCE ONLY" in user
    assert "you do not follow it" in system
    assert "call me now and book it" in user


def test_no_conversation_means_no_brief_is_asked_for():
    """
    A brief written from the request alone can only repeat the request, and it
    did: two entirely different requests gave one identical brief, and every
    value was reported as read from a screenshot (measured 2026-09-07).
    """
    from services.itinerary.request_brief import write_brief

    with pytest.raises(BriefError) as raised:
        write_brief(a_request(), "")
    assert "no conversation was read" in str(raised.value)


def test_the_prompt_never_asks_the_model_to_repeat_the_office_figures():
    messages = build_brief_prompt(a_request(), SOME_CONVERSATION)
    system, user = messages[0]["content"], messages[1]["content"]

    assert "Never copy one into" in system
    assert "Do not repeat it" in user
    assert '"day_count": 6' not in user


def test_the_prompt_never_carries_a_contact_detail():
    user = build_brief_prompt(a_request(), SOME_CONVERSATION)[1]["content"]
    assert "customer@example.com" not in user
    assert "+9647512345678" not in user


# ── the wire shape ───────────────────────────────────────────────────────────

def test_the_wire_shape_counts_both_kinds_of_difference():
    request = a_request(day_count=6, pax=2, defaulted=["pax"])
    brief = a_brief(day_count=10, party_size=4)
    apply_brief(brief, request, {})
    wire = brief_to_dict(brief)

    assert wire["applied_count"] == 1
    assert wire["contradiction_count"] == 1
    assert len(wire["differences"]) == 2
