"""
tests/test_run_record.py

A run record is evidence, and evidence a later run may rewrite is not evidence.

Two defects these guard against. A sealed record that still takes steps would
let a second press move the finish time and the answers of work that already
ended. A record that reported itself complete while a step was untested would
let a reviewer read an unread conversation as an empty one, which is the same
defect phase four fixed in `SequenceCheck.is_clean`.

Per tests/TESTING_STANDARD.md: no network, no mail, and no model.
"""
import sys
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.itinerary import run_record  # noqa: E402
from services.itinerary.run_record import (  # noqa: E402
    OUTCOME_DONE,
    OUTCOME_FAILED,
    STEP_BRIEF,
    STEP_EXTRACT,
    STEP_READ_LINK,
    STEPS,
    ItineraryRun,
    RunError,
    iter_runs,
    load,
    record_step,
    run_to_dict,
    seal,
    start_run,
    untested_step,
)


@pytest.fixture(autouse=True)
def a_directory_of_its_own(tmp_path, monkeypatch):
    """Every test writes into its own directory and leaves nothing behind."""
    monkeypatch.setattr(run_record, "ITINERARY_RUN_DIR", str(tmp_path))


# ── the seal ─────────────────────────────────────────────────────────────────

def test_a_sealed_run_takes_no_more_steps():
    run = start_run("dr-test")
    record_step(run, STEP_READ_LINK, OUTCOME_DONE, statement="found a link")
    seal(run)

    with pytest.raises(RunError):
        record_step(run, STEP_EXTRACT, OUTCOME_DONE, statement="read it")


def test_a_run_is_sealed_once():
    run = seal(start_run("dr-test"))
    with pytest.raises(RunError):
        seal(run)


def test_an_unknown_step_name_is_a_caller_bug():
    run = start_run("dr-test")
    with pytest.raises(RunError):
        record_step(run, "invented", OUTCOME_DONE)


def test_an_unknown_outcome_is_a_caller_bug():
    run = start_run("dr-test")
    with pytest.raises(RunError):
        record_step(run, STEP_READ_LINK, "maybe")


# ── complete means every step ran ────────────────────────────────────────────

def test_a_run_with_an_untested_step_is_not_complete():
    run = start_run("dr-test")
    for name in STEPS:
        record_step(run, name, OUTCOME_DONE)
    seal(run)
    assert run.is_complete is True

    second = start_run("dr-second")
    for name in STEPS[:-1]:
        record_step(second, name, OUTCOME_DONE)
    untested_step(second, STEPS[-1], "the layer is off")
    seal(second)

    assert second.failures == []
    assert second.is_complete is False
    assert second.untested == [f"{STEPS[-1]}: the layer is off"]


def test_a_run_with_a_failed_step_is_not_complete():
    run = start_run("dr-test")
    for name in STEPS[:-1]:
        record_step(run, name, OUTCOME_DONE)
    record_step(run, STEPS[-1], OUTCOME_FAILED, statement="it raised")
    seal(run)
    assert run.is_complete is False


def test_an_unsealed_run_is_never_complete():
    run = start_run("dr-test")
    for name in STEPS:
        record_step(run, name, OUTCOME_DONE)
    assert run.is_complete is False


# ── the record on disk ───────────────────────────────────────────────────────

def test_every_step_is_on_disk_before_the_next_one_starts():
    """A crash in step 4 must keep everything steps 1 to 3 produced."""
    run = start_run("dr-test")
    record_step(run, STEP_READ_LINK, OUTCOME_DONE, statement="found a link")
    reloaded = load(run.run_id)
    assert reloaded is not None
    assert [s.name for s in reloaded.steps] == [STEP_READ_LINK]


def test_a_second_press_writes_a_second_record():
    first = seal(start_run("dr-test"))
    second = start_run("dr-test")

    assert second.run_id != first.run_id
    assert load(first.run_id) is not None
    assert {r.run_id for r in iter_runs("dr-test")} == {first.run_id, second.run_id}


def test_runs_are_filtered_by_draft():
    start_run("dr-one")
    start_run("dr-two")
    assert [r.draft_id for r in iter_runs("dr-one")] == ["dr-one"]
    assert len(list(iter_runs())) == 2


def test_an_unreadable_record_does_not_hide_the_others(tmp_path):
    good = start_run("dr-test")
    (tmp_path / "run-broken.json").write_text("{not json", encoding="utf-8")
    assert [r.run_id for r in iter_runs()] == [good.run_id]


# ── what a reader receives ───────────────────────────────────────────────────

def test_the_record_names_every_endpoint_the_run_reached():
    run = start_run("dr-test")
    record_step(run, STEP_EXTRACT, OUTCOME_DONE, where="box:11434 qwen3.8:27b")
    record_step(run, STEP_BRIEF, OUTCOME_DONE, where="box:11434 qwen3.8:27b")
    assert run.endpoints_reached == ["box:11434 qwen3.8:27b"]


def test_a_step_that_reached_no_model_names_no_endpoint():
    run = start_run("dr-test")
    step = untested_step(run, STEP_BRIEF, "the layer is off")
    assert step.reached_a_model is False
    assert run.endpoints_reached == []


def test_the_wire_shape_keeps_the_two_halves_apart():
    run = start_run("dr-test")
    untested_step(run, STEP_EXTRACT, "no screenshot")
    seal(run)
    wire = run_to_dict(run)

    assert wire["is_sealed"] is True
    assert wire["is_complete"] is False
    assert wire["untested"] == ["extract: no screenshot"]
    assert wire["failures"] == []


def test_an_empty_run_reports_nothing_complete():
    run = ItineraryRun(run_id="run-x", draft_id="dr-test")
    assert run.is_complete is False
