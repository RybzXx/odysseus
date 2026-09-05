"""
tests/test_offers_provenance.py

Tests that every artifact derived from the offer corpus says which corpus it
came from, and that a reader can tell a current artifact from a stale one.

The defect these guard against is not a wrong number. It is a right number that
went stale in silence: a coverage figure measured over 2 offers sat beside a
review queue built from 68, and nothing on disk or on the page said so.

Per tests/TESTING_STANDARD.md: tmp_path in every test that touches disk, and no
test writes an artifact under the real data directory.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.offers import offer_store, recover  # noqa: E402
from services.offers.gap_report import load_summary, save_summary  # noqa: E402
from services.offers.offer_store import (  # noqa: E402
    PROVENANCE_CURRENT,
    PROVENANCE_STALE,
    PROVENANCE_UNKNOWN,
    corpus_fingerprint,
    corpus_provenance,
)
from services.offers.proposals import TemplateProposal  # noqa: E402


def _store_record(root, name, days=1):
    """One offer directory holding the record the fingerprint stats."""
    directory = Path(root) / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "offer.json").write_text(
        json.dumps({"message_id": f"<{name}@x>", "days": [{"day_number": n}
                                                          for n in range(1, days + 1)]}),
        encoding="utf-8",
    )
    return directory


@pytest.fixture
def corpus_root(tmp_path, monkeypatch):
    root = tmp_path / "offer_corpus"
    root.mkdir()
    monkeypatch.setattr(offer_store, "OFFER_CORPUS_DIR", str(root))
    return root


# --- the fingerprint -------------------------------------------------------

def test_fingerprint_is_stable_while_the_corpus_is_unchanged(corpus_root):
    _store_record(corpus_root, "a")
    _store_record(corpus_root, "b")
    assert corpus_fingerprint()["fingerprint"] == corpus_fingerprint()["fingerprint"]


def test_fingerprint_counts_only_directories_holding_a_record(corpus_root):
    _store_record(corpus_root, "a")
    (corpus_root / "half-written").mkdir()
    assert corpus_fingerprint()["count"] == 1


def test_fingerprint_changes_when_an_offer_is_added(corpus_root):
    _store_record(corpus_root, "a")
    before = corpus_fingerprint()["fingerprint"]
    _store_record(corpus_root, "b")
    assert corpus_fingerprint()["fingerprint"] != before


def test_fingerprint_changes_when_a_record_is_rewritten_in_place(corpus_root):
    """
    A reparse rewrites offer.json and leaves the set of offers the same. A
    fingerprint over membership alone would call that corpus unchanged, and the
    gap measured over it would be wrong while reading as current.
    """
    directory = _store_record(corpus_root, "a", days=1)
    before = corpus_fingerprint()["fingerprint"]

    record = directory / "offer.json"
    stat = record.stat()
    record.write_text(json.dumps({"message_id": "<a@x>",
                                  "days": [{"day_number": 1}, {"day_number": 2}]}),
                      encoding="utf-8")
    os.utime(record, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    assert corpus_fingerprint()["fingerprint"] != before


def test_fingerprint_of_an_absent_corpus_is_empty_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(offer_store, "OFFER_CORPUS_DIR", str(tmp_path / "nothing-here"))
    stamp = corpus_fingerprint()
    assert stamp["count"] == 0
    assert stamp["fingerprint"]


# --- finding one message's offers ------------------------------------------

def test_a_message_lookup_returns_every_offer_that_message_carried(corpus_root, monkeypatch):
    """
    One email can carry a group offer and an individual one. The evidence
    handler holds a day key, which names the message but not the attachment, so
    the lookup must return both.
    """
    from services.offers.models import OfferDay, SentOffer
    from services.offers.offer_store import offers_of_message, store_offer
    monkeypatch.setattr(offer_store, "OFFER_CORPUS_DIR", str(corpus_root))
    for attachment in ("group.pdf", "individual.pdf"):
        store_offer(
            SentOffer(message_id="<1@x>", subject="Iraq", sent_at=None,
                      attachment_name=attachment, days=[OfferDay(1, "day one", "Mosul")]),
            b"%PDF-", "day one",
        )
    assert len(offers_of_message("<1@x>")) == 2


def test_a_message_lookup_reads_nothing_for_an_unknown_message(corpus_root):
    from services.offers.offer_store import offers_of_message
    _store_record(corpus_root, "a")
    assert offers_of_message("<nobody@x>") == []


# --- reading a stamp -------------------------------------------------------

def test_a_stamp_from_this_corpus_reads_as_current(corpus_root):
    _store_record(corpus_root, "a")
    assert corpus_provenance(corpus_fingerprint())["state"] == PROVENANCE_CURRENT


def test_a_stamp_from_another_corpus_reads_as_stale(corpus_root):
    _store_record(corpus_root, "a")
    stamp = corpus_fingerprint()
    _store_record(corpus_root, "b")
    provenance = corpus_provenance(stamp)
    assert provenance["state"] == PROVENANCE_STALE
    assert provenance["stored"]["count"] == 1
    assert provenance["live"]["count"] == 2


def test_an_unstamped_artifact_reads_as_unknown_never_as_current(corpus_root):
    _store_record(corpus_root, "a")
    assert corpus_provenance(None)["state"] == PROVENANCE_UNKNOWN
    assert corpus_provenance({})["state"] == PROVENANCE_UNKNOWN


def test_a_supplied_live_stamp_is_used_rather_than_the_disk(corpus_root):
    """One live fingerprint serves a whole queue, so it must be honoured."""
    _store_record(corpus_root, "a")
    live = {"count": 99, "fingerprint": "not-this-corpus"}
    assert corpus_provenance(corpus_fingerprint(), live)["state"] == PROVENANCE_STALE


# --- the gap summary -------------------------------------------------------

def test_a_summary_written_before_stamping_loads_and_reads_as_unknown(tmp_path):
    path = tmp_path / "catalogue_gap.json"
    path.write_text(json.dumps({"offers": 2, "coverage": 0.3333}), encoding="utf-8")
    summary = load_summary(str(path))
    assert summary["offers"] == 2
    assert corpus_provenance(summary.get("corpus"))["state"] == PROVENANCE_UNKNOWN


def test_a_summary_round_trips_its_stamp(tmp_path, corpus_root):
    _store_record(corpus_root, "a")
    stamp = corpus_fingerprint()
    path = tmp_path / "catalogue_gap.json"
    save_summary({"corpus": stamp, "offers": 1}, str(path))
    assert load_summary(str(path))["corpus"]["fingerprint"] == stamp["fingerprint"]


# --- the proposal queue ----------------------------------------------------

def test_a_proposal_file_without_a_corpus_field_loads_as_unstamped():
    """The 48 proposals on disk predate the field. They must load, not raise."""
    proposal = TemplateProposal(proposal_id="new-1", kind="new", fields={})
    assert proposal.corpus is None
    assert corpus_provenance(proposal.corpus,
                             {"fingerprint": "x"})["state"] == PROVENANCE_UNKNOWN


def test_a_proposal_carries_the_stamp_it_was_built_with(corpus_root):
    _store_record(corpus_root, "a")
    stamp = corpus_fingerprint()
    proposal = TemplateProposal(proposal_id="new-1", kind="new", fields={}, corpus=stamp)
    assert corpus_provenance(proposal.corpus, stamp)["state"] == PROVENANCE_CURRENT


# --- the failure record ----------------------------------------------------

def test_a_run_that_finds_no_failures_still_writes_a_record(tmp_path, corpus_root):
    """
    A skipped write leaves the previous record standing, and no reader can tell
    it from a record of the run that just finished.
    """
    path = tmp_path / "offer_recovery_failures.json"
    recover.write_failure_record([], {"months": 24, "accounts": ["book@x"]}, str(path))
    record = recover.load_failure_record(str(path))
    assert record["failures"] == []
    assert record["scope"]["months"] == 24
    assert record["corpus"]["count"] == 0


def test_the_failure_record_names_the_scope_it_covered(tmp_path, corpus_root):
    path = tmp_path / "offer_recovery_failures.json"
    recover.write_failure_record(
        [{"attachment": "x.pdf", "reason": "no itinerary in this document"}],
        {"months": 24, "accounts": ["book@x"], "dry_run": False},
        str(path),
    )
    assert recover.load_failure_record(str(path))["scope"]["accounts"] == ["book@x"]


def test_a_legacy_bare_list_record_loads_as_unknown_provenance(tmp_path):
    path = tmp_path / "offer_recovery_failures.json"
    path.write_text(json.dumps([{"attachment": "x.pdf", "reason": "no text recovered"}]),
                    encoding="utf-8")
    record = recover.load_failure_record(str(path))
    assert len(record["failures"]) == 1
    assert corpus_provenance(record["corpus"],
                             {"fingerprint": "x"})["state"] == PROVENANCE_UNKNOWN


def test_an_absent_failure_record_is_none_not_an_error(tmp_path):
    assert recover.load_failure_record(str(tmp_path / "nothing.json")) is None


# --- cost ------------------------------------------------------------------

def test_the_fingerprint_is_cheap_enough_to_take_on_every_request(corpus_root):
    """
    The review page stamps on read. A fingerprint that costs a read of every
    record would put the page back where it started, which is a handler holding
    a request open over corpus-wide work.
    """
    for index in range(400):
        _store_record(corpus_root, f"offer-{index:04d}")
    started = time.perf_counter()
    stamp = corpus_fingerprint()
    elapsed = time.perf_counter() - started
    assert stamp["count"] == 400
    assert elapsed < 0.25, f"fingerprint over 400 offers took {elapsed:.3f}s"


# --- unspaced extraction ---------------------------------------------------

def test_text_that_kept_its_spaces_is_not_called_unspaced():
    from services.offers.offer_text import looks_unspaced
    assert not looks_unspaced("Meet and greet, and fast track visa from the airport.")


def test_text_that_lost_every_space_is_called_unspaced():
    from services.offers.offer_text import looks_unspaced
    assert looks_unspaced("Meetandgreet,andfasttrackvisafromtheairporttothehotel.Atouroftheoldcityfollowsinthelateafternoon,thendinnerbythriver.")


def test_empty_text_is_not_called_unspaced():
    """
    Nothing can be said about a string with no characters. Calling it broken
    would send it for repair on every pass, forever.
    """
    from services.offers.offer_text import looks_unspaced
    assert not looks_unspaced("")
    assert not looks_unspaced("   \n ")


def test_the_threshold_sits_in_the_measured_gap():
    """
    Affected days measured between 0.000 and 0.027, text read correctly between
    0.147 and 0.151. A threshold outside that gap would either miss a broken day
    or send a good one for repair.
    """
    from services.offers.offer_text import MIN_SPACE_RATIO
    assert 0.03 < MIN_SPACE_RATIO < 0.14


def test_reextraction_repairs_a_stored_offer_and_leaves_the_attachment_alone(
        corpus_root, monkeypatch):
    import services.offers.offer_text as offer_text
    from services.offers.models import OfferDay, SentOffer
    from services.offers.offer_store import reextract_stored, store_offer

    monkeypatch.setattr(offer_store, "OFFER_CORPUS_DIR", str(corpus_root))
    unspaced = ("Day1\nMeetandgreet,andfasttrackvisafromtheairporttothehotel."
                "Atourofthecityfollows,thendinnerbytheriverbeforewereturn.")
    spaced = "Day 1\nMeet and greet, and fast track visa from the airport to the hotel."
    attachment = b"%PDF-1.4 stand-in"
    store_offer(
        SentOffer(message_id="<1@x>", subject="Iraq", sent_at=None,
                  attachment_name="offer.pdf", days=[OfferDay(1, unspaced, "")]),
        attachment, unspaced,
    )
    monkeypatch.setattr(offer_text, "extract_offer_text", lambda data, name: spaced)

    outcome = reextract_stored()
    assert outcome["unspaced"] == 1
    assert outcome["repaired"] == 1

    directory = next(corpus_root.iterdir())
    assert (directory / "text.txt").read_text(encoding="utf-8") == spaced
    assert (directory / "source.pdf").read_bytes() == attachment
    record = json.loads((directory / "offer.json").read_text(encoding="utf-8"))
    assert any("re-extracted" in w for w in record["extraction_warnings"])


def test_reextraction_leaves_a_well_spaced_offer_untouched(corpus_root, monkeypatch):
    import services.offers.offer_text as offer_text
    from services.offers.models import OfferDay, SentOffer
    from services.offers.offer_store import reextract_stored, store_offer

    monkeypatch.setattr(offer_store, "OFFER_CORPUS_DIR", str(corpus_root))
    spaced = "Day 1\nMeet and greet at the airport, then drive to the hotel."
    store_offer(
        SentOffer(message_id="<2@x>", subject="Iraq", sent_at=None,
                  attachment_name="offer.pdf", days=[OfferDay(1, spaced, "")]),
        b"%PDF-", spaced,
    )
    directory = next(corpus_root.iterdir())
    before = (directory / "offer.json").read_bytes()

    def _never_called(data, name):
        raise AssertionError("a well-spaced offer must not be extracted again")
    monkeypatch.setattr(offer_text, "extract_offer_text", _never_called)

    outcome = reextract_stored()
    assert outcome["unspaced"] == 0
    assert outcome["repaired"] == 0
    assert (directory / "offer.json").read_bytes() == before


def test_a_second_read_that_is_still_unspaced_changes_nothing(corpus_root, monkeypatch):
    import services.offers.offer_text as offer_text
    from services.offers.models import OfferDay, SentOffer
    from services.offers.offer_store import reextract_stored, store_offer

    monkeypatch.setattr(offer_store, "OFFER_CORPUS_DIR", str(corpus_root))
    unspaced = ("Day1\nMeetandgreet,andfasttrackvisafromtheairporttothehotel."
                "Atourofthecityfollows,thendinnerbytheriverbeforewereturn.")
    store_offer(
        SentOffer(message_id="<3@x>", subject="Iraq", sent_at=None,
                  attachment_name="offer.pdf", days=[OfferDay(1, unspaced, "")]),
        b"%PDF-", unspaced,
    )
    directory = next(corpus_root.iterdir())
    before = (directory / "offer.json").read_bytes()
    monkeypatch.setattr(offer_text, "extract_offer_text", lambda data, name: unspaced)

    outcome = reextract_stored()
    assert outcome["repaired"] == 0
    assert outcome["still_unspaced"] == ["offer.pdf"]
    assert (directory / "offer.json").read_bytes() == before


def test_the_pdf_reader_keeps_pypdf_when_its_text_is_fine(monkeypatch):
    """The second reader is asked only about a document the first one mangled."""
    import services.offers.offer_text as offer_text
    monkeypatch.setattr(offer_text, "_pdf_text_pypdf", lambda data: "Meet and greet at the airport.")

    def _never_called(data):
        raise AssertionError("PyMuPDF must not be asked about text that is already spaced")
    monkeypatch.setattr(offer_text, "_pdf_text_pymupdf", _never_called)
    assert offer_text._pdf_text(b"x") == "Meet and greet at the airport."


def test_the_pdf_reader_falls_back_when_the_first_read_lost_its_spaces(monkeypatch):
    import services.offers.offer_text as offer_text
    mangled = ("Meetandgreetattheairport,thenweheadtothehotelandrestbefore"
               "thefirstfulldayofthetourbeginstomorrowmorningatnineoclock.")
    clean = ("Meet and greet at the airport, then we head to the hotel and rest "
             "before the first full day of the tour begins tomorrow morning.")
    monkeypatch.setattr(offer_text, "_pdf_text_pypdf", lambda data: mangled)
    monkeypatch.setattr(offer_text, "_pdf_text_pymupdf", lambda data: clean)
    assert offer_text._pdf_text(b"x") == clean


def test_the_pdf_reader_keeps_the_first_read_when_the_fallback_is_no_better(monkeypatch):
    import services.offers.offer_text as offer_text
    mangled = ("Meetandgreetattheairport,thenweheadtothehotelandrestbefore"
               "thefirstfulldayofthetourbeginstomorrowmorningatnineoclock.")
    monkeypatch.setattr(offer_text, "_pdf_text_pypdf", lambda data: mangled)
    monkeypatch.setattr(offer_text, "_pdf_text_pymupdf", lambda data: None)
    assert offer_text._pdf_text(b"x") == mangled


def test_text_too_short_to_judge_is_not_called_unspaced():
    """
    A day reading "Arrival" holds no spaces because it is one word. Five such
    days in one .docx were sent for repair by a ratio test that judged them.
    """
    from services.offers.offer_text import looks_unspaced
    assert not looks_unspaced("Arrival")
    assert not looks_unspaced("Uplistsikhe")


def test_reextraction_follows_one_damaged_day_in_a_document_that_reads_well(
        corpus_root, monkeypatch):
    """
    The day is the unit that gets matched. One document scored 0.094 across the
    whole file while its third day read "Visit theSulaymaniyahMuseum".
    """
    import services.offers.offer_text as offer_text
    from services.offers.models import OfferDay, SentOffer
    from services.offers.offer_store import reextract_stored, store_offer

    monkeypatch.setattr(offer_store, "OFFER_CORPUS_DIR", str(corpus_root))
    good_day = ("Meet and greet at the airport, then drive to the hotel and rest "
                "before the first full day of the tour begins tomorrow morning.")
    bad_day = ("VisittheSulaymaniyahMuseum,atreasuretroveofKurdishhistory,thenwalk"
               "throughthebazaarandreturntothehotelbeforesunsetfortheevening.")
    whole = good_day + "\n" + good_day + "\n" + bad_day
    store_offer(
        SentOffer(message_id="<4@x>", subject="Iraq", sent_at=None,
                  attachment_name="offer.pdf",
                  days=[OfferDay(1, good_day, ""), OfferDay(2, good_day, ""),
                        OfferDay(3, bad_day, "")]),
        b"%PDF-", whole,
    )
    from services.offers.offer_text import looks_unspaced
    assert not looks_unspaced(whole), "the document must read well overall"

    repaired = good_day + "\n" + good_day + "\n" + good_day
    monkeypatch.setattr(offer_text, "extract_offer_text", lambda data, name: repaired)
    outcome = reextract_stored()
    assert outcome["unspaced"] == 1
    assert outcome["repaired"] == 1


# --- progress reporting ----------------------------------------------------

def test_the_analysis_reports_how_far_each_stage_has_got():
    """
    A full pass takes about fifteen minutes and printed one line before it, then
    nothing. The module measures and never prints, so the caller supplies the
    callback and a handler that wants silence passes none.
    """
    from services.offers.gap_report import (
        PROGRESS_EVERY,
        STAGE_CLUSTERING,
        STAGE_SCORING,
        analyse_catalogue_gap,
    )
    from services.offers.models import OfferDay, SentOffer

    day_text = ("Drive south to the marshes, board a mashoof through the reed "
                "channels, and return to the hotel before sunset.")
    offers = [SentOffer(message_id=f"<{n}@x>", subject="Iraq", sent_at=None,
                        attachment_name="offer.pdf",
                        days=[OfferDay(1, f"{day_text} Variant {n}.", "Nasiriyah")])
              for n in range(PROGRESS_EVERY * 2 + 5)]

    seen = []
    analyse_catalogue_gap(offers, {"MO1": "an unrelated day in Mosul"},
                          on_progress=lambda *args: seen.append(args))
    stages = {stage for stage, _, _, _ in seen}
    assert STAGE_SCORING in stages
    assert STAGE_CLUSTERING in stages
    for stage in (STAGE_SCORING, STAGE_CLUSTERING):
        last = [row for row in seen if row[0] == stage][-1]
        assert last[1] == last[2], f"{stage} must report its own completion"


def test_the_analysis_stays_silent_when_no_callback_is_given():
    """An HTTP handler passes none, and the module must print nothing."""
    from services.offers.gap_report import analyse_catalogue_gap
    from services.offers.models import OfferDay, SentOffer
    offers = [SentOffer(message_id="<1@x>", subject="Iraq", sent_at=None,
                        attachment_name="offer.pdf",
                        days=[OfferDay(1, "a day in Mosul with the old city", "Mosul")])]
    report = analyse_catalogue_gap(offers, {"MO1": "a day in Mosul with the old city"})
    assert report.total_days == 1
