"""
tests/test_rule_book.py

Tests for WP4a: a counted rule survives the run that found it, says what it is
counted out of, and knows whether the sheet has it.

Two defects these guard against. A re-count that reports every rule as changed
would make the sheet sync rewrite the whole tab for nothing. A rule the corpus
stops supporting, deleted rather than retired, would leave the sheet holding it
with nothing to say it should go.

Per tests/TESTING_STANDARD.md: tmp_path in every test that touches disk, and no
test writes under the real data directory.
"""
import json
import sys
from pathlib import Path

import pytest

ODYSSEUS_ROOT = str(Path(__file__).resolve().parent.parent)
if ODYSSEUS_ROOT not in sys.path:
    sys.path.insert(0, ODYSSEUS_ROOT)

from services.offers import rule_book  # noqa: E402
from services.offers.rule_book import (  # noqa: E402
    BOOK_COUNTED,
    BOOK_JUDGED,
    VERDICT_AGREES,
    VERDICT_DISAGREES,
    VERDICT_SILENT,
    JudgedRule,
    RuleBookError,
    RuleRecord,
    book_summary,
    iter_judged_rules,
    iter_rules,
    judged_summary,
    load_judged_rule,
    load_rule,
    mark_synced,
    rule_id_for,
    save_counted_report,
    save_judged_rule,
    save_rule,
)
from services.offers.rule_counter import (  # noqa: E402
    FAMILY_FIRST_NIGHT,
    FAMILY_MOVE,
    CountedRule,
    RuleReport,
)

CORPUS = {"count": 335, "fingerprint": "abc123", "stamped_at": "2026-09-06T12:00:00+00:00"}


@pytest.fixture
def books(tmp_path, monkeypatch):
    monkeypatch.setattr(rule_book, "AI_RULES_DIR", str(tmp_path / "ai_rules"))
    return tmp_path / "ai_rules"


def _report(*rules):
    report = RuleReport()
    report.rules.extend(rules)
    report.offers_counted = 289
    return report


def _first_night(city, count, total=289):
    return CountedRule(family=FAMILY_FIRST_NIGHT, subject=city, count=count,
                       total=total,
                       statement=f"{count} of {total} trips spend the first night in {city}.")


# ── the id names the rule, and it is readable ────────────────────────────────

def test_a_rule_id_is_stable_for_one_rule():
    assert rule_id_for(FAMILY_FIRST_NIGHT, "Baghdad") == \
           rule_id_for(FAMILY_FIRST_NIGHT, "Baghdad")


def test_a_rule_id_says_what_the_rule_is_about():
    assert "baghdad" in rule_id_for(FAMILY_FIRST_NIGHT, "Baghdad")
    assert "first_night" in rule_id_for(FAMILY_FIRST_NIGHT, "Baghdad")


def test_a_move_id_keeps_both_cities_apart():
    there = rule_id_for(FAMILY_MOVE, "Erbil -> Baghdad")
    back = rule_id_for(FAMILY_MOVE, "Baghdad -> Erbil")
    assert there != back


def test_a_subject_with_a_path_separator_cannot_escape_the_book(books):
    rule_id = rule_id_for(FAMILY_MOVE, "../../etc -> passwd")
    assert "/" not in rule_id and "\\" not in rule_id


# ── eleven fields, and every one is written ─────────────────────────────────

def test_a_saved_rule_holds_all_eleven_fields(books):
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    path = books / BOOK_COUNTED / f"{rule_id_for(FAMILY_FIRST_NIGHT, 'Baghdad')}.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert set(stored) == {
        "rule_id", "family", "subject", "statement", "count", "total", "share",
        "corpus", "counted_at", "synced_at", "synced_hash",
    }


def test_a_rule_states_its_count_and_its_denominator(books):
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    record = load_rule(BOOK_COUNTED, rule_id_for(FAMILY_FIRST_NIGHT, "Baghdad"))
    assert record.count == 199
    assert record.total == 289
    assert record.share == pytest.approx(199 / 289, abs=1e-4)


def test_a_rule_names_the_corpus_it_was_counted_over(books):
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    record = load_rule(BOOK_COUNTED, rule_id_for(FAMILY_FIRST_NIGHT, "Baghdad"))
    assert record.corpus["fingerprint"] == "abc123"
    assert record.corpus["count"] == 335


# ── syncing ─────────────────────────────────────────────────────────────────

def test_a_rule_that_was_never_synced_reads_as_never_synced(books):
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    record = load_rule(BOOK_COUNTED, rule_id_for(FAMILY_FIRST_NIGHT, "Baghdad"))
    assert record.synced_at is None
    assert record.synced_hash is None
    assert record.changed_since_sync is False


def test_marking_a_rule_synced_records_what_was_synced(books):
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    rule_id = rule_id_for(FAMILY_FIRST_NIGHT, "Baghdad")
    record = mark_synced(BOOK_COUNTED, rule_id)
    assert record.synced_at is not None
    assert record.synced_hash == record.content_hash
    assert record.changed_since_sync is False


def test_a_recount_does_not_forget_that_the_sheet_has_the_rule(books):
    """The regression: a re-count that clears synced_at re-pushes the whole tab."""
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    rule_id = rule_id_for(FAMILY_FIRST_NIGHT, "Baghdad")
    mark_synced(BOOK_COUNTED, rule_id)

    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    record = load_rule(BOOK_COUNTED, rule_id)
    assert record.synced_at is not None


def test_a_rule_whose_count_moved_reads_as_changed_since_its_sync(books):
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    rule_id = rule_id_for(FAMILY_FIRST_NIGHT, "Baghdad")
    mark_synced(BOOK_COUNTED, rule_id)

    save_counted_report(_report(_first_night("Baghdad", 205)), corpus=CORPUS)
    record = load_rule(BOOK_COUNTED, rule_id)
    assert record.count == 205
    assert record.changed_since_sync is True


def test_the_hash_ignores_when_the_rule_was_counted(books):
    """Two runs finding the same rule must not read as a change."""
    first = RuleRecord(rule_id="x", family=FAMILY_FIRST_NIGHT, subject="Baghdad",
                       statement="s", count=199, total=289, share=0.68,
                       counted_at="2026-09-06T10:00:00+00:00")
    second = RuleRecord(rule_id="x", family=FAMILY_FIRST_NIGHT, subject="Baghdad",
                        statement="s", count=199, total=289, share=0.68,
                        counted_at="2026-09-07T10:00:00+00:00")
    assert first.content_hash == second.content_hash


# ── an unchanged rule is not rewritten ──────────────────────────────────────

def test_a_second_identical_pass_writes_nothing(books):
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    outcome = save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    assert outcome["written"] == 0
    assert outcome["unchanged"] == 1


# ── a rule the corpus drops is retired, not deleted ─────────────────────────

def test_a_rule_the_corpus_no_longer_supports_is_retired(books):
    save_counted_report(
        _report(_first_night("Baghdad", 199), _first_night("Basra", 46)), corpus=CORPUS)
    outcome = save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)

    assert outcome["retired"] == 1
    retired = load_rule(BOOK_COUNTED, rule_id_for(FAMILY_FIRST_NIGHT, "Basra"))
    assert retired is not None, "a retired rule stays, so the sync can see it go"
    assert retired.count == 0
    assert retired.statement.startswith("[retired]")


def test_a_rule_is_retired_once(books):
    save_counted_report(
        _report(_first_night("Baghdad", 199), _first_night("Basra", 46)), corpus=CORPUS)
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    outcome = save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    assert outcome["retired"] == 0


def test_a_retired_rule_that_returns_is_counted_again(books):
    save_counted_report(
        _report(_first_night("Baghdad", 199), _first_night("Basra", 46)), corpus=CORPUS)
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    save_counted_report(
        _report(_first_night("Baghdad", 199), _first_night("Basra", 51)), corpus=CORPUS)

    record = load_rule(BOOK_COUNTED, rule_id_for(FAMILY_FIRST_NIGHT, "Basra"))
    assert record.count == 51
    assert not record.statement.startswith("[retired]")


# ── the two books stay apart ────────────────────────────────────────────────

def test_the_counted_reader_refuses_the_judged_book(books):
    """The regression: a judgement read through the counted reader as a count."""
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    with pytest.raises(RuleBookError):
        list(iter_rules(BOOK_JUDGED))
    assert len(list(iter_rules(BOOK_COUNTED))) == 1


def test_an_unknown_book_is_refused(books):
    with pytest.raises(RuleBookError):
        list(iter_rules("everything"))


def test_a_rule_with_no_id_is_refused(books):
    with pytest.raises(RuleBookError):
        save_rule(BOOK_COUNTED, RuleRecord(rule_id="", family="f", subject="s",
                                           statement="", count=0, total=0, share=0.0))


def test_marking_a_missing_rule_is_refused(books):
    with pytest.raises(RuleBookError):
        mark_synced(BOOK_COUNTED, "no-such-rule")


# ── the book reports its own shape ──────────────────────────────────────────

def test_the_summary_counts_by_family_and_by_sync(books):
    save_counted_report(_report(
        _first_night("Baghdad", 199),
        _first_night("Basra", 46),
        CountedRule(family=FAMILY_MOVE, subject="Erbil -> Erbil", count=52,
                    total=71, statement="After a night in Erbil, ..."),
    ), corpus=CORPUS)
    mark_synced(BOOK_COUNTED, rule_id_for(FAMILY_FIRST_NIGHT, "Baghdad"))

    summary = book_summary(BOOK_COUNTED)
    assert summary["count"] == 3
    assert summary["families"] == {FAMILY_FIRST_NIGHT: 2, FAMILY_MOVE: 1}
    assert summary["synced"] == 1
    assert summary["unsynced"] == 2
    assert summary["changed_since_sync"] == 0


def test_an_empty_book_reports_nothing(books):
    summary = book_summary(BOOK_COUNTED)
    assert summary["count"] == 0
    assert summary["families"] == {}


def test_an_unreadable_rule_file_does_not_hide_the_book(books):
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    (books / BOOK_COUNTED / "broken.json").write_text("{not json", encoding="utf-8")
    assert len(list(iter_rules(BOOK_COUNTED))) == 1


# ── the judged book ─────────────────────────────────────────────────────────

def _judged(statement, **extra):
    return JudgedRule(rule_id=extra.pop("rule_id", "jr-1"), statement=statement,
                      comment_id="cm-1", comment_text="end in Erbil, not Baghdad",
                      draft_id="dr-1", **extra)


def test_the_family_name_matches_the_counter():
    """The move family is named in two modules. They must not drift apart."""
    assert rule_book.FAMILY_MOVE_NAME == FAMILY_MOVE


def test_a_judged_rule_keeps_the_comment_that_produced_it(books):
    save_judged_rule(_judged("Trips for one traveller end in Erbil.",
                             corrected_sequence=["ARRBG", "BG1CT", "MOBKHEB"]))
    stored = load_judged_rule("jr-1")
    assert stored.comment_text == "end in Erbil, not Baghdad"
    assert stored.corrected_sequence == ["ARRBG", "BG1CT", "MOBKHEB"]
    assert stored.draft_id == "dr-1"


def test_a_judged_rule_the_corpus_has_not_seen_is_silent_not_refused(books):
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    save_judged_rule(_judged("Groups of four prefer a slower first day."))
    stored = load_judged_rule("jr-1")
    assert stored.corpus_verdict == VERDICT_SILENT
    assert stored.corpus_evidence == ""


def test_a_judged_rule_the_corpus_leads_on_agrees(books):
    save_counted_report(
        _report(_first_night("Baghdad", 199), _first_night("Basra", 46)), corpus=CORPUS)
    save_judged_rule(_judged("Start in Baghdad.",
                             family=FAMILY_FIRST_NIGHT, subject="Baghdad"))
    stored = load_judged_rule("jr-1")
    assert stored.corpus_verdict == VERDICT_AGREES
    assert "199 of 289" in stored.corpus_evidence


def test_a_judged_rule_the_corpus_outranks_disagrees(books):
    save_counted_report(
        _report(_first_night("Baghdad", 199), _first_night("Basra", 46)), corpus=CORPUS)
    save_judged_rule(_judged("Start in Basra.",
                             family=FAMILY_FIRST_NIGHT, subject="Basra"))
    stored = load_judged_rule("jr-1")
    assert stored.corpus_verdict == VERDICT_DISAGREES
    assert "Baghdad" in stored.corpus_evidence


def test_a_claim_the_corpus_never_counted_disagrees_when_the_family_has_a_leader(books):
    save_counted_report(_report(_first_night("Baghdad", 199)), corpus=CORPUS)
    save_judged_rule(_judged("Start in Mosul.",
                             family=FAMILY_FIRST_NIGHT, subject="Mosul"))
    assert load_judged_rule("jr-1").corpus_verdict == VERDICT_DISAGREES


def test_a_move_is_judged_against_the_city_it_leaves(books):
    """A move counts out of one city, so its rivals are the other moves out of it."""
    save_counted_report(_report(
        CountedRule(family=FAMILY_MOVE, subject="Erbil -> Erbil", count=52,
                    total=71, statement="After a night in Erbil, again 52 of 71."),
        CountedRule(family=FAMILY_MOVE, subject="Baghdad -> Mosul", count=171,
                    total=709, statement="After a night in Baghdad, Mosul 171 of 709."),
    ), corpus=CORPUS)

    save_judged_rule(_judged("After Erbil, stay in Erbil.", rule_id="jr-erbil",
                             family=FAMILY_MOVE, subject="Erbil -> Erbil"))
    assert load_judged_rule("jr-erbil").corpus_verdict == VERDICT_AGREES


def test_a_judged_rule_with_no_statement_is_refused(books):
    with pytest.raises(RuleBookError):
        save_judged_rule(JudgedRule(rule_id="jr-1", statement="   "))


def test_a_judged_rule_with_no_id_is_refused(books):
    with pytest.raises(RuleBookError):
        save_judged_rule(JudgedRule(rule_id="", statement="a rule"))


def test_the_judged_summary_counts_by_verdict(books):
    save_counted_report(
        _report(_first_night("Baghdad", 199), _first_night("Basra", 46)), corpus=CORPUS)
    save_judged_rule(_judged("Start in Baghdad.", rule_id="jr-a",
                             family=FAMILY_FIRST_NIGHT, subject="Baghdad"))
    save_judged_rule(_judged("Start in Basra.", rule_id="jr-b",
                             family=FAMILY_FIRST_NIGHT, subject="Basra"))
    save_judged_rule(_judged("Slower first day for families.", rule_id="jr-c"))

    summary = judged_summary()
    assert summary["count"] == 3
    assert summary["verdicts"][VERDICT_AGREES] == 1
    assert summary["verdicts"][VERDICT_DISAGREES] == 1
    assert summary["verdicts"][VERDICT_SILENT] == 1
    assert summary["unsynced"] == 3


def test_one_comment_states_one_rule(books):
    """A retry after a half-finished accept must overwrite, not duplicate."""
    from services.offers.rule_book import rule_id_for_comment

    rule_id = rule_id_for_comment("cm-abc123")
    save_judged_rule(_judged("Start in Baghdad.", rule_id=rule_id))
    save_judged_rule(_judged("Start in Baghdad, always.", rule_id=rule_id))
    assert len(list(iter_judged_rules())) == 1
    assert load_judged_rule(rule_id).statement == "Start in Baghdad, always."


def test_a_comment_id_with_a_path_separator_cannot_escape_the_book(books):
    from services.offers.rule_book import rule_id_for_comment

    assert "/" not in rule_id_for_comment("../../etc/passwd")
    assert "\\" not in rule_id_for_comment("..\\..\\windows")


def test_a_rewritten_judged_rule_keeps_its_sync(books):
    save_judged_rule(_judged("Start in Baghdad."))
    stored = load_judged_rule("jr-1")
    stored.synced_at = "2026-09-06T12:00:00+00:00"
    stored.synced_hash = stored.content_hash
    save_judged_rule(stored)

    save_judged_rule(_judged("Start in Baghdad, always."))
    again = load_judged_rule("jr-1")
    assert again.synced_at == "2026-09-06T12:00:00+00:00"
    assert again.changed_since_sync is True
