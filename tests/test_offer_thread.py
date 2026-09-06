"""
tests/test_offer_thread.py

Tests that a sent offer carries the conversation it answered, and that a reader
can tell how each part of that conversation was recovered.

The defect these guard against is a silent absence. The first Sent-folder walk
kept the attachment and discarded the message it arrived on, and nothing on disk
said so. A record with no body and a record whose message carried no body look
the same to a reader who only asks "is there text?" (ws-03 WP9).

Per tests/TESTING_STANDARD.md: tmp_path in every test that touches disk, and no
test writes an artifact under the real data directory. No test reads mail.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.offers import offer_store, offer_thread  # noqa: E402
from services.offers.models import OfferDay, SentOffer  # noqa: E402
from services.offers.offer_store import (  # noqa: E402
    load_offer,
    offer_dir,
    store_offer,
    store_thread_source,
    stored_body,
)
from services.offers.offer_thread import (  # noqa: E402
    TURN_HEADER,
    TURN_QUOTE,
    assemble_threads,
    thread_of,
)

# A sent reply that quotes the request it answers. The quoted block is the only
# surviving copy of what the customer asked for.
REPLY_BODY = """Dear Magdalena,

Please find the 8-day itinerary attached.

On Mon, 3 Feb 2026 at 10:12, Magdalena <magdalena@example.com> wrote:
> We are four people and we would like to see Babylon and Erbil.
> Eight days in April would suit us.
"""


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """An empty corpus under tmp_path, with both modules pointed at it."""
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
        days=[OfferDay(day_number=1, text="Arrival", overnight_city="Baghdad")],
        **extra,
    )


def _store_unwalked(message_id, attachment):
    """
    A record as the first Sent-folder walk left it: no body files, no headers.

    Written through `offer_dir` so `load_offer` finds it. A record placed under
    any other directory name is unreachable by every reader in the store.
    """
    directory = Path(offer_dir(message_id, attachment))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "offer.json").write_text(
        json.dumps({"message_id": message_id,
                    "attachment_name": attachment, "days": []}),
        encoding="utf-8")
    return directory


# ── the body is stored, and absence is distinguishable ────────────────────────

def test_a_stored_offer_carries_its_message_body(corpus):
    store_offer(_offer("<a@bilweekend.iq>"), b"data", "day text",
                body_text=REPLY_BODY, body_html="")
    body = stored_body(offer_dir("<a@bilweekend.iq>", "trip.pdf"))
    assert body is not None
    assert "Babylon and Erbil" in body[0]


def test_a_message_with_no_body_is_not_the_same_as_one_never_read(corpus):
    """The regression: both look empty, and only one means the walk did not run."""
    store_offer(_offer("<read@bilweekend.iq>"), b"data", "day text",
                body_text="", body_html="")
    directory = _store_unwalked("<old@bilweekend.iq>", "old.pdf")

    assert stored_body(offer_dir("<read@bilweekend.iq>", "trip.pdf")) == ("", "")
    assert stored_body(str(directory)) is None


# ── the headers survive the round trip ────────────────────────────────────────

def test_thread_headers_survive_a_store_and_load(corpus):
    offer = _offer("<b@bilweekend.iq>",
                   in_reply_to="<req@example.com>",
                   references=["<first@example.com>", "<req@example.com>"])
    store_offer(offer, b"data", "day text")
    loaded = load_offer("<b@bilweekend.iq>", "trip.pdf")
    assert loaded.in_reply_to == "<req@example.com>"
    assert loaded.references == ["<first@example.com>", "<req@example.com>"]


def test_a_record_written_before_this_field_existed_reads_as_empty(corpus):
    """335 records predate these fields. Absent must read as empty, not crash."""
    _store_unwalked("<legacy@bilweekend.iq>", "old.pdf")
    loaded = load_offer("<legacy@bilweekend.iq>", "old.pdf")
    assert loaded.in_reply_to == ""
    assert loaded.references == []


# ── the backfill adds context and never rewrites the attachment ───────────────

def test_the_backfill_adds_a_body_without_touching_the_attachment(corpus):
    store_offer(_offer("<c@bilweekend.iq>", data=b"original"), b"original", "day text")
    source = offer_dir("<c@bilweekend.iq>", "trip.pdf") + "/source.pdf"
    before = Path(source).read_bytes()

    written = store_thread_source("<c@bilweekend.iq>", REPLY_BODY, "",
                                  "<req@example.com>", ["<req@example.com>"])

    assert len(written) == 1
    assert Path(source).read_bytes() == before, "invariant 1.1: source is never rewritten"
    loaded = load_offer("<c@bilweekend.iq>", "trip.pdf")
    assert loaded.in_reply_to == "<req@example.com>"


def test_the_backfill_leaves_the_extracted_text_alone(corpus):
    store_offer(_offer("<d@bilweekend.iq>"), b"data", "the extracted day text")
    store_thread_source("<d@bilweekend.iq>", REPLY_BODY, "")
    text = Path(offer_dir("<d@bilweekend.iq>", "trip.pdf") + "/text.txt")
    assert text.read_text(encoding="utf-8") == "the extracted day text"


def test_the_backfill_reaches_both_offers_of_one_message(corpus):
    """One email can carry a group and an individual version of one trip."""
    store_offer(_offer("<e@bilweekend.iq>", "individual.pdf", b"one"), b"one", "text one")
    store_offer(_offer("<e@bilweekend.iq>", "group.pdf", b"two"), b"two", "text two")
    written = store_thread_source("<e@bilweekend.iq>", REPLY_BODY, "")
    assert len(written) == 2


def test_the_backfill_skips_a_message_the_corpus_does_not_hold(corpus):
    assert store_thread_source("<absent@bilweekend.iq>", REPLY_BODY, "") == []


# ── the thread is recovered, and each turn says how ───────────────────────────

def test_a_quoted_request_becomes_a_turn(corpus):
    store_offer(_offer("<f@bilweekend.iq>"), b"data", "day text",
                body_text=REPLY_BODY, body_html="")
    thread = thread_of("<f@bilweekend.iq>", "trip.pdf")
    assert thread.body_captured is True
    assert thread.quote_turns, "a Re: body with a quoted block must yield a turn"
    assert all(turn.source == TURN_QUOTE for turn in thread.quote_turns)


def test_an_earlier_offer_in_the_chain_becomes_a_header_turn(corpus):
    store_offer(_offer("<first@bilweekend.iq>", "first.pdf", b"one",
                       subject="Iraq trip — first draft"),
                b"one", "text one")
    store_offer(_offer("<second@bilweekend.iq>", "second.pdf", b"two",
                       references=["<first@bilweekend.iq>"]),
                b"two", "text two")

    thread = thread_of("<second@bilweekend.iq>", "second.pdf")
    header_turns = thread.header_turns
    assert len(header_turns) == 1
    assert header_turns[0].source == TURN_HEADER
    assert header_turns[0].message_id == "<first@bilweekend.iq>"
    assert header_turns[0].subject == "Iraq trip — first draft"


def test_a_named_message_the_corpus_lacks_is_reported_not_invented(corpus):
    store_offer(_offer("<g@bilweekend.iq>", references=["<gone@example.com>"]),
                b"data", "day text")
    thread = thread_of("<g@bilweekend.iq>", "trip.pdf")
    assert thread.unresolved_ids == ["<gone@example.com>"]
    assert thread.header_turns == []


def test_the_offer_never_names_itself_as_an_earlier_turn(corpus):
    store_offer(_offer("<h@bilweekend.iq>",
                       in_reply_to="<h@bilweekend.iq>",
                       references=["<h@bilweekend.iq>"]),
                b"data", "day text")
    thread = thread_of("<h@bilweekend.iq>", "trip.pdf")
    assert thread.chain_ids == []
    assert thread.header_turns == []


def test_in_reply_to_and_references_name_the_parent_once(corpus):
    """Most mailers repeat the parent in both headers. It is one message."""
    store_offer(_offer("<i@bilweekend.iq>",
                       in_reply_to="<req@example.com>",
                       references=["<first@example.com>", "<req@example.com>"]),
                b"data", "day text")
    thread = thread_of("<i@bilweekend.iq>", "trip.pdf")
    assert thread.chain_ids == ["<first@example.com>", "<req@example.com>"]


def test_a_body_that_was_never_captured_is_not_a_thread_that_is_absent(corpus):
    _store_unwalked("<j@bilweekend.iq>", "j.pdf")
    thread = thread_of("<j@bilweekend.iq>", "j.pdf")
    assert thread.body_captured is False
    assert thread.turns == []


def test_thread_of_returns_none_for_an_offer_the_corpus_does_not_hold(corpus):
    assert thread_of("<nothing@bilweekend.iq>", "x.pdf") is None


# ── the corpus-wide report names its failures ─────────────────────────────────

def test_the_report_names_what_did_not_recover(corpus):
    store_offer(_offer("<k@bilweekend.iq>", "recovered.pdf"), b"data", "day text",
                body_text=REPLY_BODY, body_html="")
    store_offer(_offer("<l@bilweekend.iq>", "bare.pdf"), b"data", "day text",
                body_text="Thank you, the itinerary is attached.", body_html="")

    outcome = assemble_threads()
    assert outcome["examined"] == 2
    assert outcome["body_captured"] == 2
    assert outcome["recovered"] == 1
    assert len(outcome["not_recovered"]) == 1
    assert "bare.pdf" in outcome["not_recovered"][0]


def test_the_report_says_when_a_body_was_never_captured(corpus):
    _store_unwalked("<m@bilweekend.iq>", "m.pdf")
    outcome = assemble_threads()
    assert outcome["body_captured"] == 0
    assert "body never captured" in outcome["not_recovered"][0]


def test_the_report_counts_nothing_over_an_empty_corpus(corpus):
    outcome = assemble_threads()
    assert outcome["examined"] == 0
    assert outcome["not_recovered"] == []
