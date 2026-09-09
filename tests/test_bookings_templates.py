"""
tests/test_bookings_templates.py

The reply a website registration gets, and the days behind its price.

Every expectation here comes from `book@bilweekend.com`, read on 2026-09-09.
The tests hold operations to their own wording rather than to a rewrite of it,
so a change to the text has to be a decision somebody made.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.bookings.templates import (  # noqa: E402
    DEPOSIT_USD,
    SIGNATURE_WHEN_UNKNOWN,
    TEMPLATE_DEPOSIT,
    TEMPLATE_QUOTE,
    UnfilledPlaceholder,
    first_name_of,
    raw_templates,
    render_quote,
    signature_for,
    template_for_tour_type,
)
from services.bookings.tour_day_codes import (  # noqa: E402
    TOUR_DAY_CODES,
    day_codes_for,
    shortfall_for,
)


# ------------------------------------------------------- which template ----

@pytest.mark.parametrize("tour_type,expected", [
    ("Group Expedition", TEMPLATE_DEPOSIT),
    ("Private Trips", TEMPLATE_QUOTE),
    ("Experience", TEMPLATE_QUOTE),
])
def test_tour_type_picks_the_template(tour_type, expected):
    """The three types the website stores each answer."""
    assert template_for_tour_type(tour_type) == expected


def test_tour_type_is_read_case_and_space_insensitively():
    assert template_for_tour_type("  group expedition ") == TEMPLATE_DEPOSIT


@pytest.mark.parametrize("tour_type", ["", None, "Day Tour", "Adventure"])
def test_an_unknown_type_answers_none(tour_type):
    """
    None is the answer the panel shows, not a default it hides.

    The one observed mismatch sent a private party of two the group template,
    which offered them a shared room. Guessing costs more than refusing.
    """
    assert template_for_tour_type(tour_type) is None


def test_price_is_not_consulted():
    """
    Four Group Expedition tours price at 0 and still take the deposit template.

    This is the rule ws-bd D1 chose over selecting on price.
    """
    assert template_for_tour_type("Group Expedition") == TEMPLATE_DEPOSIT


# ------------------------------------------------------------ greeting ----

@pytest.mark.parametrize("full,expected", [
    ("Giulio Porroni", "Giulio"),
    ("CARLOS GUIDO TRAMUTOLA", "Carlos"),
    ("Matheus sambaquy giacomet", "Matheus"),
    ("  Evelina  Gabor  ", "Evelina"),
    ("Cher", "Cher"),
    ("", ""),
    (None, ""),
])
def test_first_name(full, expected):
    """Capitals are corrected: 'CARLOS...' was answered 'Dear Carlos'."""
    assert first_name_of(full) == expected


# ----------------------------------------------------------- signature ----

def test_worklist_operator_reaches_the_signature():
    """The worklist says 'Nooriya' where the signature says 'Noor Ahmed'."""
    assert "Noor Ahmed" in signature_for("Nooriya")
    assert signature_for("Mustafa") == "Mustafa Simani"


@pytest.mark.parametrize("operator", ["", None, "Someone New"])
def test_an_unknown_operator_signs_as_the_company(operator):
    """A draft must not invent a colleague's name."""
    assert signature_for(operator) == SIGNATURE_WHEN_UNKNOWN


# --------------------------------------------------------- the quote ----

def test_quote_matches_the_sent_wording():
    """
    Giulio Porroni, 2026-08-31, three people, confirm block asked for.
    """
    q = render_quote(tour_name="The Marshes & Ur", party_size=3,
                     ask_to_confirm=True, operator="Mustafa",
                     first_name="Giulio", full_name="Giulio Porroni")
    assert q.name == TEMPLATE_QUOTE
    assert q.subject == "The Marshes & Ur for 3 PAX - Giulio Porroni"
    assert q.body.startswith("Dear Giulio,")
    assert "3 passengers (PAX)" in q.body
    assert "A clear scan of your passports" in q.body
    assert q.body.rstrip().endswith("Mustafa Simani")


def test_a_single_day_quote_asks_for_nothing():
    """
    Evelina Gabor, 2026-09-05: the itinerary alone, no ask list (ws-bd D3).
    """
    q = render_quote(tour_name="Baghdad Day Trip", party_size=1,
                     ask_to_confirm=False, operator="Nooriya",
                     first_name="Evelina", full_name="Evelina Gabor")
    assert q.subject == "Baghdad Day Trip - Evelina Gabor"
    assert "PAX" not in q.body
    assert "scan of your passports" not in q.body


def test_the_quote_names_no_price():
    """
    The price rides in the attached itinerary, as every observed send did.

    A number in the body that disagrees with the document is a number the
    customer finds.
    """
    q = render_quote(tour_name="The Original Tour Private", party_size=2,
                     ask_to_confirm=True,
                     first_name="Chris", full_name="Chris Coetzee")
    assert "$" not in q.body


def test_an_unfilled_placeholder_raises():
    """
    Post violated is an implementation bug, and it must not reach a customer.
    """
    from services.bookings import templates

    original = templates.QUOTE_BODY
    templates.QUOTE_BODY = original + "\n{unknown_field}"
    try:
        with pytest.raises(UnfilledPlaceholder):
            render_quote(tour_name="T", party_size=1, ask_to_confirm=False,
                         first_name="A", full_name="A B")
    finally:
        templates.QUOTE_BODY = original


# ------------------------------------------------------ raw templates ----

def test_raw_templates_carry_placeholders_for_the_website():
    """
    The Overview tab shows these before any pricing runs (ws-bd A1, 8.1).
    """
    deposit, quote = raw_templates()
    assert deposit.name == TEMPLATE_DEPOSIT
    assert quote.name == TEMPLATE_QUOTE
    assert "{first_name}" in deposit.body
    assert "{tour_name}" in deposit.body
    assert "{month_year}" in deposit.subject


def test_the_deposit_body_is_ready_to_fill_by_the_website():
    """
    The deposit and the bank block are resolved here, not on the website.

    A group departure needs no pricing, so the website fills the rest itself
    (ws-bd 8.1). It must not also have to know the amount.
    """
    deposit, _ = raw_templates()
    assert f"${DEPOSIT_USD} deposit" in deposit.body
    assert "GB34 REVO 0099 7049 5646 21" in deposit.body
    assert "{deposit}" not in deposit.body
    assert "{payment_details}" not in deposit.body


def test_the_deposit_asks_for_every_observed_item():
    """
    Two sends nine days apart each asked for something the other left out.
    Both are kept.
    """
    deposit, _ = raw_templates()
    for line in ("single or shared room", "scan of your passport",
                 "white background", "WhatsApp"):
        assert line in deposit.body


# --------------------------------------------------------- day codes ----

def test_every_mapped_tour_has_codes():
    assert len(TOUR_DAY_CODES) == 6
    for slug, codes in TOUR_DAY_CODES.items():
        assert codes, slug


@pytest.mark.parametrize("slug,day_count", [
    ("marshes-ur-2-days", 2),
    ("babylon-day-trip", 1),
    ("baghdad-day-trip", 1),
    ("center-south-5-days", 5),
    ("center-north-5-days", 9),
    ("the-original-tour-private", 8),
])
def test_code_count_matches_the_published_day_count(slug, day_count):
    """
    Read from each tour's own itinerary on 2026-09-09.

    `center-north-5-days` really does run nine days. Its slug says five and its
    name says neither, which ws-bd leaves alone.
    """
    assert len(day_codes_for(slug)) == day_count


def test_every_mapped_code_is_a_real_template():
    """A code with no template prices nothing, and would fail at run time."""
    import glob
    import os as _os

    known = {_os.path.basename(p)[:-5]
             for p in glob.glob("services/offers/data/templates/*.json")}
    for slug, codes in TOUR_DAY_CODES.items():
        for code in codes:
            assert code in known, f"{slug} names unknown template {code}"


def test_a_tours_own_codes_win():
    """An operator corrects a wrong default without a deploy (ws-bd D4)."""
    assert day_codes_for("marshes-ur-2-days", ["NA1", "NA2BA"]) == ("NA1", "NA2BA")


def test_an_empty_code_list_falls_back_to_the_map():
    """
    Empty is 'this tour names none', not 'this tour has none'.

    Every tour carries an empty list today, and reading it as an answer would
    price nothing anywhere.
    """
    assert day_codes_for("babylon-day-trip", []) == ("BB",)
    assert day_codes_for("babylon-day-trip", None) == ("BB",)


def test_an_unmapped_tour_prices_nothing():
    """The loud failure: a renamed slug drops out rather than pricing stale days."""
    assert day_codes_for("no-such-tour") == ()


def test_the_known_shortfall_is_reported():
    """
    Whoever reads the Baghdad day-trip price must learn the museum is missing.
    """
    assert "museum" in shortfall_for("baghdad-day-trip").lower()
    assert shortfall_for("marshes-ur-2-days") == ""


# ------------------------------------------------- the withheld greeting ----

def test_a_pricing_run_leaves_the_name_open():
    """
    A run reads a tour and a party size and never a person.

    Filling the greeting would mean the run had read the registrant, which arms
    the external-context gate and forbids that same run from reporting its
    answer. The website substitutes both names afterwards (ws-bd D6, D7).
    """
    q = render_quote(tour_name="Babylon Day Trip", party_size=2,
                     ask_to_confirm=True, operator="Mustafa")
    assert "{first_name}" in q.body
    assert "{full_name}" in q.subject
    assert q.subject.startswith("Babylon Day Trip for 2 PAX")
    # Everything the run does know is already filled.
    assert "{tour_name}" not in q.body
    assert "{signature}" not in q.body
    assert "{rate_line}" not in q.body
    assert q.body.rstrip().endswith("Mustafa Simani")


def test_the_withheld_render_still_refuses_other_placeholders():
    """Leaving the name open must not become permission to leave anything open."""
    from services.bookings import templates

    original = templates.QUOTE_BODY
    templates.QUOTE_BODY = original + "\n{unknown_field}"
    try:
        with pytest.raises(UnfilledPlaceholder):
            render_quote(tour_name="T", party_size=1, ask_to_confirm=False)
    finally:
        templates.QUOTE_BODY = original


# ------------------------------------------------------- filing a draft ----
#
# `draft_append` is the one path in this package that handles a customer's
# name. These tests hold the reason that is safe: it builds a message and files
# it, and it reasons about nothing.

def test_the_appender_imports_no_model():
    """
    The invariant the whole design rests on, checked rather than asserted.

    A model reached from here would be a model reading text a stranger wrote,
    inside a process that can write to a mailbox.
    """
    import inspect

    from services.bookings import draft_append

    source = inspect.getsource(draft_append)
    for forbidden in ("openai", "ollama", "anthropic", "llm", "chat_completion",
                      "generate(", "model="):
        assert forbidden not in source.lower(), forbidden


def test_build_message_leaves_the_text_alone():
    """The operator read this on screen. Filing must not edit it."""
    from services.bookings.draft_append import build_message

    body = "Dear Giulio,\n\nPlease find the requested itinerary.\n"
    message = build_message(recipient="a@example.com", subject="Ur & The Marshes",
                            body=body, from_address="book@bilweekend.com",
                            display_name="Bilweekend Booking")
    assert message["To"] == "a@example.com"
    assert message["Subject"] == "Ur & The Marshes"
    assert message["From"] == "Bilweekend Booking <book@bilweekend.com>"
    assert message.get_content() == body
    assert message.get_content_type() == "text/plain"


def test_an_empty_append_is_refused_before_any_connection():
    """
    Pre violated is a caller bug, and it must not open a mailbox to find out.

    The server action reads the recipient from the booking, so an empty one
    means the caller skipped it.
    """
    from services.bookings.draft_append import file_draft

    outcome = file_draft({"id": "x", "recipient": "", "subject": "s", "body": "b"})
    assert not outcome.ok
    assert "recipient" in outcome.error


def test_the_result_payload_says_folder_or_error():
    """The route refuses a result carrying neither."""
    from services.bookings.draft_append import DraftAppendOutcome

    ok = DraftAppendOutcome(folder="[Gmail]/Drafts", appended_uid="42")
    assert ok.as_result_payload() == {
        "folder": "[Gmail]/Drafts", "appendedUid": "42", "error": None}

    bad = DraftAppendOutcome(error="no drafts folder")
    assert bad.as_result_payload()["error"] == "no drafts folder"
    assert bad.as_result_payload()["folder"] is None


def test_uid_is_optional():
    """
    Gmail usually answers APPEND with APPENDUID and is not required to.

    An empty uid means the append landed and the server did not name it, which
    is evidence enough. Reading it as a failure would file every draft twice.
    """
    from services.bookings.draft_append import _uid_from

    assert _uid_from([b"[APPENDUID 12 4321] (Success)"]) == "4321"
    assert _uid_from([b"(Success)"]) == ""
