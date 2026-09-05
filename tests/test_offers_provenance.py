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
