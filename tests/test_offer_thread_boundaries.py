"""
tests/test_offer_thread_boundaries.py

Boundary attack on the WP9 thread capture. These are written to fail.

Per tests/TESTING_STANDARD.md: tmp_path in every test that touches disk, and no
test reads mail.
"""
import email
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.offers import offer_store, offer_thread, sent_offers  # noqa: E402
from services.offers.models import OfferDay, SentOffer  # noqa: E402
from services.offers.offer_store import (  # noqa: E402
    load_offer,
    offer_dir,
    reextract_stored,
    reparse_stored,
    store_offer,
    store_thread_source,
    stored_body,
)
from services.offers.offer_thread import assemble_threads, thread_of  # noqa: E402
from services.offers.sent_offers import (  # noqa: E402
    _message_body,
    _message_key,
    _thread_headers,
)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    root = tmp_path / "offer_corpus"
    root.mkdir()
    monkeypatch.setattr(offer_store, "OFFER_CORPUS_DIR", str(root))
    monkeypatch.setattr(offer_thread, "OFFER_CORPUS_DIR", str(root))
    return root


def _offer(message_id, attachment="trip.pdf", data=b"data", **extra):
    return SentOffer(
        message_id=message_id,
        subject=extra.pop("subject", "Re: Iraq trip"),
        sent_at=extra.pop("sent_at", datetime(2026, 2, 4, tzinfo=timezone.utc)),
        attachment_name=attachment,
        attachment_mime="application/pdf",
        attachment_bytes=len(data),
        days=[OfferDay(day_number=1, text="Day 1 Arrival at Baghdad", overnight_city="Baghdad")],
        **extra,
    )


# ── A. the other corpus passes must not wipe the thread fields ────────────────

def test_reparse_keeps_the_thread_headers(corpus):
    """A --reparse after a thread walk must not discard in_reply_to."""
    store_offer(_offer("<a@bilweekend.iq>",
                       in_reply_to="<req@example.com>",
                       references=["<req@example.com>"]),
                b"data", "Day 1 Arrival at Baghdad\nDay 2 Babylon")
    reparse_stored()
    loaded = load_offer("<a@bilweekend.iq>", "trip.pdf")
    assert loaded.in_reply_to == "<req@example.com>"
    assert loaded.references == ["<req@example.com>"]


def test_reextract_keeps_the_thread_headers(corpus, monkeypatch):
    """A --reextract repair must not discard references either."""
    from services.offers import offer_text

    unspaced = "Day1Meetandgreet,andfasttrackvisafromtheairportonarrival"
    store_offer(_offer("<b@bilweekend.iq>",
                       in_reply_to="<req@example.com>",
                       references=["<first@example.com>", "<req@example.com>"]),
                b"data", unspaced)
    monkeypatch.setattr(
        offer_text, "extract_offer_text",
        lambda data, name: "Day 1 Meet and greet, and fast track visa from the airport")
    reextract_stored()
    loaded = load_offer("<b@bilweekend.iq>", "trip.pdf")
    assert loaded.in_reply_to == "<req@example.com>"
    assert loaded.references == ["<first@example.com>", "<req@example.com>"]


def test_reparse_does_not_delete_the_captured_body(corpus):
    store_offer(_offer("<c@bilweekend.iq>"), b"data", "Day 1 Arrival",
                body_text="quoted request here", body_html="")
    reparse_stored()
    assert stored_body(offer_dir("<c@bilweekend.iq>", "trip.pdf")) is not None


# ── B. a message with no Message-ID can never be backfilled ───────────────────

def _message(headers, body="body"):
    raw = "".join(f"{name}: {value}\r\n" for name, value in headers)
    return email.message_from_string(raw + "Content-Type: text/plain\r\n\r\n" + body)


def test_a_message_with_no_id_keys_the_same_way_in_both_walks(corpus):
    """
    An IMAP sequence number changes between sessions, so an offer stored under
    one could never be found again by the thread walk.
    """
    headers = [("Date", "Thu, 5 Feb 2026 10:00:00 +0300"),
               ("Subject", "Iraq trip"),
               ("To", "client@example.com"),
               ("From", "book@bilweekend.com")]
    first = _message_key(_message(headers))
    second = _message_key(_message(headers))
    assert first == second, "the fallback key must not move between reads"
    assert first.startswith("nomsgid-")

    store_offer(_offer(first), b"data", "Day 1 Arrival")
    assert store_thread_source(first, "quoted request", ""), \
        "an offer with no Message-ID must still be reachable"


def test_the_message_id_is_the_key_when_the_message_carries_one(corpus):
    key = _message_key(_message([("Message-ID", "<real@bilweekend.iq>")]))
    assert key == "<real@bilweekend.iq>"


# ── C. offers_of_message matches by prefix ───────────────────────────────────

def test_a_referenced_id_does_not_match_a_longer_stored_id(corpus):
    """
    offers_of_message matches directories by slug prefix. Two ids that differ
    only by a suffix share a prefix, so a chain can name the wrong offer.
    """
    store_offer(_offer("<abc@xy>", "long.pdf", subject="the longer id"),
                b"data", "Day 1 Arrival")
    store_offer(_offer("<later@bilweekend.iq>", "later.pdf",
                       references=["<abc@x>"]),
                b"data", "Day 1 Arrival")

    thread = thread_of("<later@bilweekend.iq>", "later.pdf")
    assert thread.header_turns == [], \
        "<abc@x> is not stored; <abc@xy> must not answer for it"
    assert thread.unresolved_ids == ["<abc@x>"]


# ── D. a naive cutoff against tz-aware records ───────────────────────────────

def test_assemble_threads_accepts_a_naive_cutoff(corpus):
    """Every stored sent_at is tz-aware. A naive cutoff must not raise."""
    store_offer(_offer("<d@bilweekend.iq>"), b"data", "Day 1 Arrival",
                body_text="quoted", body_html="")
    outcome = assemble_threads(since=datetime(2026, 1, 1))
    assert outcome["examined"] == 1


# ── E. "recovered" must mean an earlier turn, not a turn count ───────────────

def test_a_body_with_no_quoted_history_is_not_recovered(corpus):
    """
    parse_thread can emit more than one level-0 turn for one unquoted body.
    `recovered` counts turns, so it can call that a recovered thread.
    """
    body = "Dear Simone,\n\nThe itinerary is attached.\n\nBest regards,\nNoor"
    store_offer(_offer("<e@bilweekend.iq>"), b"data", "Day 1 Arrival",
                body_text=body, body_html="")
    thread = thread_of("<e@bilweekend.iq>", "trip.pdf")
    assert all(turn.level == 0 for turn in thread.quote_turns)
    assert thread.recovered is False, "no quoted history is not a recovered thread"


# ── F. a forwarded message's inner body ──────────────────────────────────────

def test_a_forwarded_message_does_not_supply_the_outer_body():
    """
    message.walk() descends into a message/rfc822 part. Its inner text/plain
    carries no filename, so it can be taken as the sent message's own body.
    """
    raw = (
        "From: noor@bilweekend.iq\r\n"
        "Subject: Fwd: request\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="B"\r\n'
        "\r\n"
        "--B\r\n"
        "Content-Type: message/rfc822\r\n"
        "\r\n"
        "From: client@example.com\r\n"
        "Subject: request\r\n"
        "Content-Type: text/plain\r\n"
        "\r\n"
        "INNER FORWARDED TEXT\r\n"
        "--B--\r\n"
    )
    plain, _ = _message_body(email.message_from_string(raw))
    assert "INNER FORWARDED TEXT" not in plain, \
        "a forwarded message's body is not the sent message's body"


# ── G. reference ids without angle brackets ─────────────────────────────────

def test_a_reference_id_without_brackets_is_kept():
    """Some mailers write References without angle brackets."""
    raw = (
        "From: noor@bilweekend.iq\r\n"
        "References: bare-id@example.com <bracketed@example.com>\r\n"
        "Content-Type: text/plain\r\n"
        "\r\n"
        "body\r\n"
    )
    _, references = _thread_headers(email.message_from_string(raw))
    assert references == ["<bracketed@example.com>"], \
        "a bracketed id wins when the header mixes the two shapes"


def test_reference_ids_with_no_brackets_at_all_are_kept():
    """A header written entirely without brackets must not read as empty."""
    raw = (
        "From: noor@bilweekend.iq\r\n"
        "References: first@example.com second@example.com\r\n"
        "Content-Type: text/plain\r\n"
        "\r\n"
        "body\r\n"
    )
    _, references = _thread_headers(email.message_from_string(raw))
    assert references == ["<first@example.com>", "<second@example.com>"]


def test_a_repeated_reference_id_is_named_once():
    raw = (
        "From: noor@bilweekend.iq\r\n"
        "References: <a@example.com> <b@example.com> <a@example.com>\r\n"
        "Content-Type: text/plain\r\n"
        "\r\n"
        "body\r\n"
    )
    _, references = _thread_headers(email.message_from_string(raw))
    assert references == ["<a@example.com>", "<b@example.com>"]


def test_in_reply_to_with_a_trailing_comment_still_names_the_parent():
    """RFC 5322 allows a comment after the id. Mailers do write them."""
    raw = (
        "From: noor@bilweekend.iq\r\n"
        "In-Reply-To: <parent@example.com> (message from Simone)\r\n"
        "Content-Type: text/plain\r\n"
        "\r\n"
        "body\r\n"
    )
    in_reply_to, _ = _thread_headers(email.message_from_string(raw))
    assert in_reply_to == "<parent@example.com>"


# ── H. charset boundaries ───────────────────────────────────────────────────

def test_a_body_in_an_unknown_charset_is_still_captured():
    raw = (
        "From: noor@bilweekend.iq\r\n"
        'Content-Type: text/plain; charset="unknown-8bit"\r\n'
        "\r\n"
        "the request text\r\n"
    )
    plain, _ = _message_body(email.message_from_string(raw))
    assert "the request text" in plain


def test_a_message_with_no_text_part_gives_two_empty_strings():
    raw = (
        "From: noor@bilweekend.iq\r\n"
        'Content-Type: application/pdf; name="trip.pdf"\r\n'
        "\r\n"
        "not text\r\n"
    )
    assert _message_body(email.message_from_string(raw)) == ("", "")


# ── I. a half-written body reads as never captured ──────────────────────────

def test_one_body_file_alone_reads_as_never_captured(corpus):
    """An interrupted write must not read as a capture that happened."""
    store_offer(_offer("<i@bilweekend.iq>"), b"data", "Day 1 Arrival",
                body_text="quoted", body_html="")
    directory = Path(offer_dir("<i@bilweekend.iq>", "trip.pdf"))
    (directory / "body.html").unlink()
    assert stored_body(str(directory)) is None
