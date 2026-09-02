"""The activity log must not record a failed run as a success.

Two independent defects produced the same lie, and both are pinned here.

**Vocabulary.** `specs/system-activity-logger.md` fixes the log's statuses at
completed/running/error/fallback/halted. `TaskRun.status` is a different
vocabulary — running/success/error/aborted/skipped — and task_scheduler mirrors
`run.status` straight into the log. Untranslated, "success" reached 29 of 57
live rows on 2026-09-02: no badge style, no filter option, no place in any
count. `normalise_status` is the boundary that makes that unrepresentable.

**Classification.** `_result_is_config_error` matches three literal phrases
about missing model config, so a DNS failure fell through it; `_result_has_work`
then returned True for a report of nothing but errors, so the action returned
success. 18 of 57 rows recorded a total failure that way while the stats header
read "Errors: 0".

Every fixture string below was read from the live phone on 2026-09-02, not
invented — including the multi-account report whose three accounts all failed
name resolution, which is the exact row that rendered as a green success.
"""

import pytest

from src.builtin_actions import (
    _pass_report_failures,
    _pass_report_status,
    _result_has_work,
    _result_is_config_error,
)
from src.system_logger import LOG_STATUSES, normalise_status

# Verbatim from the live activity log.
LIVE_ALL_FAILED = (
    "[Book Bil Weekend] Error: [Errno -3] Temporary failure in name resolution\n"
    "[Personal Email (hmoha)] Error: [Errno -3] Temporary failure in name resolution\n"
    "[Secondary Personal.] Error: [Errno -3] Temporary failure in name resolution"
)
LIVE_ALL_SUCCEEDED = (
    "[Book Bil Weekend] Scanned 49 email(s) (none) · processed 3 new · created 1 calendar event(s)\n"
    "[Personal Email (hmoha)] Scanned 26 email(s) (none) · processed 3 new · 2 already cached\n"
    "[Secondary Personal.] Scanned 13 email(s) (none)"
)


# --------------------------------------------------------------------------
# Status vocabulary
# --------------------------------------------------------------------------

@pytest.mark.parametrize("legal", sorted(LOG_STATUSES))
def test_a_legal_status_passes_through_unchanged(legal):
    assert normalise_status(legal) == legal


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("success", "completed"),   # 29 live rows carried this
        ("SUCCESS", "completed"),   # case is not the caller's contract to keep
        ("  success  ", "completed"),
        ("aborted", "halted"),      # task_scheduler.py:389
        ("skipped", "halted"),      # task_scheduler.py:983
    ],
)
def test_task_run_vocabulary_is_translated(raw, expected):
    assert normalise_status(raw) == expected


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_absent_status_defaults_to_completed(empty):
    assert normalise_status(empty) == "completed"


def test_an_unknown_status_is_never_stored_raw(caplog):
    """Falsification: a new caller inventing a word must not silently widen
    the vocabulary — the CSS, the filter and the counts all key off it."""
    with caplog.at_level("WARNING"):
        assert normalise_status("mostly-fine") == "completed"
    assert "mostly-fine" in caplog.text


def test_every_normalised_value_is_in_the_vocabulary():
    """The postcondition, over every input the log has ever seen."""
    seen = ["completed", "running", "error", "fallback", "halted",
            "success", "aborted", "skipped", "ok", "", None, "nonsense"]
    assert {normalise_status(s) for s in seen} <= LOG_STATUSES


# --------------------------------------------------------------------------
# Pass-report classification
# --------------------------------------------------------------------------

def test_the_old_predicates_still_misread_the_failure():
    """Pins why a third predicate exists rather than a widened second one.

    Neither pre-existing predicate can see this failure: the config matcher
    looks for three phrases about missing models, and the work matcher looks
    for zero-counts. Both answer 'this run did work'. Keeping them honest
    about their own jobs — and adding one that knows what an error line looks
    like — is the fix; widening either would make its name a lie.
    """
    assert _result_is_config_error(LIVE_ALL_FAILED) is False
    assert _result_has_work(LIVE_ALL_FAILED) is True
    # ...which is why this one had to exist.
    assert _pass_report_status(LIVE_ALL_FAILED) == "error"


def test_every_account_failed_is_counted():
    assert _pass_report_failures(LIVE_ALL_FAILED) == (3, 3)


def test_the_all_failed_row_reads_error_not_success():
    """This is the 08:04 extract_email_events row, live, rendered green."""
    assert _pass_report_status(LIVE_ALL_FAILED) == "error"


def test_a_healthy_pass_is_untouched():
    assert _pass_report_failures(LIVE_ALL_SUCCEEDED) == (0, 3)
    assert _pass_report_status(LIVE_ALL_SUCCEEDED) is None


def test_a_partial_failure_is_degraded_not_failed():
    """Two accounts answered; one did not. The run produced real work, so it
    is not an error — but it is not clean either."""
    mixed = (
        "[Book Bil Weekend] Scanned 49 email(s) (none) · processed 3 new\n"
        "[Personal Email (hmoha)] Error: [Errno -3] Temporary failure in name resolution\n"
        "[Secondary Personal.] Scanned 13 email(s) (none)"
    )
    assert _pass_report_failures(mixed) == (1, 3)
    assert _pass_report_status(mixed) == "fallback"


def test_the_aggregator_lowercase_error_prefix_counts_too():
    """email_pollers.py:498 writes 'error:', :1361 writes 'Error:'. Matching
    only one of the two would leave half the failure paths invisible."""
    assert _pass_report_status("[Book Bil Weekend] error: connection reset") == "error"


def test_single_account_failure_needs_no_bracket():
    """With one account configured the report is bare — no '[Name] ' prefix."""
    assert _pass_report_failures("Error: [Errno -3] Temporary failure in name resolution") == (1, 1)
    assert _pass_report_status("Error: [Errno -3] Temporary failure in name resolution") == "error"


def test_single_account_success_is_untouched():
    live = "scanned 104 · urgent 5 · reply-soon 14 · info 0 · trivial 85"
    assert _pass_report_status(live) is None


def test_a_success_that_mentions_the_word_error_is_not_a_failure():
    """Falsification for a substring search. Email subjects reach these
    reports verbatim, and one of them saying "Error" must not fail the run."""
    report = (
        "[Book Bil Weekend] Scanned 49 email(s) · processed 3 new\n\n"
        "Processed:\n"
        "- **Error budget review** — _<ops@example.com>_ `travel` (updated)"
    )
    assert _pass_report_status(report) is None


def test_a_detail_block_does_not_inflate_the_account_count():
    """The 'Processed:' lines are not accounts."""
    report = (
        "scanned 12 · processed 2 new\n\n"
        "Processed:\n"
        "- one\n"
        "- two"
    )
    assert _pass_report_failures(report) == (0, 1)


@pytest.mark.parametrize("nothing", [None, "", "   ", 42, [], {}])
def test_nothing_reported_is_not_read_as_success(nothing):
    """(0, 0) means no account answered. A caller that read the first element
    alone would see zero failures and call it clean."""
    assert _pass_report_failures(nothing) == (0, 0)
    assert _pass_report_status(nothing) is None
