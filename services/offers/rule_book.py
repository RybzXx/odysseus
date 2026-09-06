"""
services/offers/rule_book.py

Where a rule is written down, so it survives the run that found it.

Two books, kept apart (ws-03 D16).

  ai_rules/counted/<rule_id>.json   a rule the corpus counted
  ai_rules/judged/<rule_id>.json    a rule a human stated

They are separate because the evidence is a different kind. A counted rule says
"199 of 289", and anyone holding the corpus can check it. A judged rule says
what a reviewer knows, and its evidence is the comment that produced it. Putting
both in one list would let a judged rule read as measured. A merge is a later
decision, and until it is made no reader sees both books at once.

Eleven fields per record. `synced_at` and `synced_hash` are the two the sheet
sync will read: a rule never synced carries None for both, and a rule whose
content moved since its last sync is what D11 refuses to overwrite.

Nothing here counts anything. `rule_counter` finds the rules; this keeps them.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterator, Optional

from src.constants import AI_RULES_DIR

# The two books. A reader is given one; nothing reads both at once.
BOOK_COUNTED = "counted"
BOOK_JUDGED = "judged"
BOOKS = (BOOK_COUNTED, BOOK_JUDGED)

_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")


class RuleBookError(Exception):
    """The book cannot satisfy a read or a write it was asked to make."""


@dataclass
class RuleRecord:
    """
    One rule as it is stored. Eleven fields, and every one is written.

    `subject` is the rule's subject exactly as the counter names it, so a move
    reads "Erbil -> Baghdad". The pair is not stored separately: `family` plus
    `subject` is the identity, and a second copy of the endpoints would be a
    second thing to keep in step.
    """
    rule_id: str
    family: str
    subject: str
    statement: str
    count: int
    total: int
    share: float
    corpus: dict = field(default_factory=dict)   # the fingerprint it was counted over
    counted_at: str = ""
    synced_at: Optional[str] = None              # None until the sheet has it
    synced_hash: Optional[str] = None            # the content hash at that sync

    @property
    def content_hash(self) -> str:
        """
        Post: a hash over what the rule says, not over when it was written.

        `counted_at` and the sync fields are left out on purpose. A re-run that
        finds the same rule with the same numbers must produce the same hash, or
        every run would look like a change and the sync would rewrite the sheet
        for nothing.
        """
        seed = json.dumps(
            [self.family, self.subject, self.statement, self.count, self.total],
            ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    @property
    def changed_since_sync(self) -> bool:
        """True when the rule says something different from what was synced."""
        return self.synced_hash is not None and self.synced_hash != self.content_hash


def rule_id_for(family: str, subject: str) -> str:
    """
    Post: a filesystem-safe id, stable for one rule across every run.

    Built from the family and the subject, which is what `CountedRule.rule_key`
    already calls the rule. A hash would be stable too and would tell a reader
    nothing; a directory listing of this book is meant to be readable.
    """
    cleaned = _UNSAFE_CHARS_RE.sub("-", f"{family}--{subject}".strip())
    return cleaned.strip("-").lower()[:120] or "unknown"


def book_dir(book: str) -> str:
    if book not in BOOKS:
        raise RuleBookError(f"unknown book: {book!r}")
    return os.path.join(AI_RULES_DIR, book)


def _path(book: str, rule_id: str) -> str:
    return os.path.join(book_dir(book), f"{rule_id}.json")


def save_rule(book: str, record: RuleRecord) -> str:
    """
    Write one rule, keeping whatever the stored copy already knew about syncing.

    Pre:  `record.rule_id` is not empty.
    Post: the file holds all eleven fields. `synced_at` and `synced_hash` come
          from the stored copy where the caller left them unset, so a re-count
          does not tell the sheet the rule was never synced.

    Blame: a caller that means to clear a sync sets both fields explicitly.
    """
    if not record.rule_id:
        raise RuleBookError("a rule record has no rule_id")
    directory = book_dir(book)
    os.makedirs(directory, exist_ok=True)

    if record.synced_at is None and record.synced_hash is None:
        stored = load_rule(book, record.rule_id)
        if stored is not None:
            record.synced_at = stored.synced_at
            record.synced_hash = stored.synced_hash

    path = _path(book, record.rule_id)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(asdict(record), fh, ensure_ascii=False, indent=2)
    os.replace(temporary, path)
    return path


def load_rule(book: str, rule_id: str) -> Optional[RuleRecord]:
    path = _path(book, rule_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return _from_dict(json.load(fh))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def _from_dict(record: dict) -> RuleRecord:
    return RuleRecord(
        rule_id=record.get("rule_id", ""),
        family=record.get("family", ""),
        subject=record.get("subject", ""),
        statement=record.get("statement", ""),
        count=int(record.get("count") or 0),
        total=int(record.get("total") or 0),
        share=float(record.get("share") or 0.0),
        corpus=dict(record.get("corpus") or {}),
        counted_at=record.get("counted_at") or "",
        synced_at=record.get("synced_at"),
        synced_hash=record.get("synced_hash"),
    )


def iter_rules(book: str) -> Iterator[RuleRecord]:
    """
    Every counted rule, by family and then commonest first.

    Pre:  `book` is BOOK_COUNTED. The judged book holds a different record and
          `iter_judged_rules` reads it; a reader that took either shape would
          let a judgement read as a measurement (D16).
    Post: a file that cannot be read is skipped, not raised — one bad rule must
          not hide the rest of the book.
    """
    if book == BOOK_JUDGED:
        raise RuleBookError(
            "the judged book holds judged rules; read it with iter_judged_rules")
    directory = book_dir(book)
    if not os.path.isdir(directory):
        return
    records = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                records.append(_from_dict(json.load(fh)))
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            continue
    records.sort(key=lambda r: (r.family, -r.share, r.subject))
    yield from records


def mark_synced(book: str, rule_id: str, at: Optional[str] = None) -> RuleRecord:
    """
    Record that the sheet now holds this rule as it currently reads.

    Pre:  the rule is in the book.
    Post: `synced_at` names the moment and `synced_hash` is the content hash at
          it, so a later change is visible as a difference rather than inferred
          from a date.
    """
    record = load_rule(book, rule_id)
    if record is None:
        raise RuleBookError(f"no rule {rule_id} in the {book} book")
    record.synced_at = at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    record.synced_hash = record.content_hash
    save_rule(book, record)
    return record


def save_counted_report(report, corpus: Optional[dict] = None) -> dict:
    """
    Write a counting pass into the counted book.

    Pre:  `report` is a RuleReport from `rule_counter.count_rules`.
          `corpus` is the fingerprint the pass was measured over.
    Post: one file per rule the pass found, each stamped with that corpus. A
          rule the pass no longer finds is retired rather than deleted, because
          the sheet may still hold it and the sync has to see it go.

    Returns counts: written, unchanged, retired.

    Blame: a report measured over one corpus and stamped with another is a
    caller bug. The stamp is a parameter so it can be taken before the pass,
    which is how `--rebuild-proposals` already does it.
    """
    from services.offers.offer_store import corpus_fingerprint

    stamp = corpus or corpus_fingerprint()
    counted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    outcome = {"written": 0, "unchanged": 0, "retired": 0, "retired_ids": []}

    seen = set()
    for rule in report.rules:
        rule_id = rule_id_for(rule.family, rule.subject)
        seen.add(rule_id)
        record = RuleRecord(
            rule_id=rule_id,
            family=rule.family,
            subject=rule.subject,
            statement=rule.statement,
            count=rule.count,
            total=rule.total,
            share=round(rule.share, 4),
            corpus=dict(stamp),
            counted_at=counted_at,
        )
        stored = load_rule(BOOK_COUNTED, rule_id)
        if stored is not None and stored.content_hash == record.content_hash:
            outcome["unchanged"] += 1
            continue
        save_rule(BOOK_COUNTED, record)
        outcome["written"] += 1

    for stored in iter_rules(BOOK_COUNTED):
        if stored.rule_id not in seen and stored.count:
            # The corpus no longer supports it. Zero the count and keep the
            # record: a deleted file tells the sheet sync nothing, and the rule
            # may still be sitting in the AIRules tab.
            stored.count = 0
            stored.share = 0.0
            stored.statement = f"[retired] {stored.statement}"
            stored.corpus = dict(stamp)
            stored.counted_at = counted_at
            save_rule(BOOK_COUNTED, stored)
            outcome["retired"] += 1
            outcome["retired_ids"].append(stored.rule_id)
    return outcome


# ── the judged book ──────────────────────────────────────────────────────────
#
# What the counted book says about a rule a human stated. It reports; it never
# refuses (ws-03 D24). A rule the corpus has not seen is often right before the
# data shows it, and the owner overrules the count rather than the reverse.
VERDICT_AGREES = "agrees"        # the corpus counted this, and it leads
VERDICT_DISAGREES = "disagrees"  # the corpus counted it, and something else leads
VERDICT_SILENT = "silent"        # the corpus says nothing about it
VERDICTS = (VERDICT_AGREES, VERDICT_DISAGREES, VERDICT_SILENT)

# Named here rather than imported, to keep this module free of a dependency on
# the counter whose output it stores. `rule_counter.FAMILY_MOVE` is the same
# string, and a test holds the two together.
FAMILY_MOVE_NAME = "move"


@dataclass
class JudgedRule:
    """
    One rule a human stated, with the feedback that produced it.

    `family` and `subject` are filled where the rule speaks about something the
    counter also measures, so the corpus can be asked. A rule about anything
    else leaves them empty and its verdict is `silent`, which is the truthful
    answer rather than a missing one.
    """
    rule_id: str
    statement: str
    comment_id: str = ""
    comment_text: str = ""
    draft_id: str = ""
    request_id: str = ""
    corrected_sequence: list = field(default_factory=list)
    family: str = ""
    subject: str = ""
    corpus_verdict: str = VERDICT_SILENT
    corpus_evidence: str = ""      # the counted statement the verdict rests on
    accepted_at: str = ""
    synced_at: Optional[str] = None
    synced_hash: Optional[str] = None

    @property
    def content_hash(self) -> str:
        seed = json.dumps([self.statement, self.family, self.subject,
                           list(self.corrected_sequence)],
                          ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    @property
    def changed_since_sync(self) -> bool:
        return self.synced_hash is not None and self.synced_hash != self.content_hash


def _move_population(subject: str) -> str:
    """Post: the city a move leaves, which is the population it counts against."""
    return subject.split("->", 1)[0].strip() if "->" in subject else subject.strip()


def corpus_verdict(family: str, subject: str) -> tuple:
    """
    What the counted book says about one claim.

    Pre:  `family` is a counter family and `subject` names the outcome claimed,
          or both are empty for a rule the counter does not measure.
    Post: (verdict, evidence). `evidence` is the counted statement the verdict
          rests on, and "" when the corpus is silent.

    A move counts against the nights spent in the city it leaves, so its rivals
    are the other moves out of that same city. Every other family counts against
    the whole population, so its rivals are the whole family.
    """
    if not family or not subject:
        return VERDICT_SILENT, ""

    rules = [r for r in iter_rules(BOOK_COUNTED) if r.family == family and r.count]
    if family == FAMILY_MOVE_NAME:
        leaving = _move_population(subject)
        rules = [r for r in rules if _move_population(r.subject) == leaving]
    if not rules:
        return VERDICT_SILENT, ""

    mine = next((r for r in rules if r.subject == subject), None)
    leader = max(rules, key=lambda r: r.count)
    if mine is None:
        return VERDICT_DISAGREES, leader.statement
    if mine.rule_id == leader.rule_id:
        return VERDICT_AGREES, mine.statement
    return VERDICT_DISAGREES, f"{mine.statement} {leader.statement}"


def rule_id_for_comment(comment_id: str) -> str:
    """
    Post: the judged rule id one comment produces, stable across every attempt.

    Derived from the comment rather than from the rule's words, so a second
    attempt after a half-finished accept overwrites the first rather than
    leaving two rules saying the same thing. One comment states one rule; a
    second rule from the same feedback is a new comment.
    """
    cleaned = _UNSAFE_CHARS_RE.sub("-", (comment_id or "").strip())
    return f"judged--{cleaned.strip('-').lower()[:100] or 'unknown'}"


def save_judged_rule(record: JudgedRule) -> str:
    """
    Write one judged rule, and ask the corpus what it makes of it.

    Pre:  `record.rule_id` and `record.statement` are not empty.
    Post: the file holds the rule, the comment that produced it, and a corpus
          verdict that reports and never refuses. Sync fields are carried over
          from the stored copy where the caller left them unset.
    """
    if not record.rule_id:
        raise RuleBookError("a judged rule has no rule_id")
    if not (record.statement or "").strip():
        raise RuleBookError("a judged rule has no statement")

    record.corpus_verdict, record.corpus_evidence = corpus_verdict(
        record.family, record.subject)
    record.accepted_at = record.accepted_at or datetime.now(
        timezone.utc).isoformat(timespec="seconds")

    directory = book_dir(BOOK_JUDGED)
    os.makedirs(directory, exist_ok=True)
    if record.synced_at is None and record.synced_hash is None:
        stored = load_judged_rule(record.rule_id)
        if stored is not None:
            record.synced_at = stored.synced_at
            record.synced_hash = stored.synced_hash

    path = _path(BOOK_JUDGED, record.rule_id)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(asdict(record), fh, ensure_ascii=False, indent=2)
    os.replace(temporary, path)
    return path


def _judged_from_dict(record: dict) -> JudgedRule:
    return JudgedRule(
        rule_id=record.get("rule_id", ""),
        statement=record.get("statement", ""),
        comment_id=record.get("comment_id", ""),
        comment_text=record.get("comment_text", ""),
        draft_id=record.get("draft_id", ""),
        request_id=record.get("request_id", ""),
        corrected_sequence=list(record.get("corrected_sequence") or []),
        family=record.get("family", ""),
        subject=record.get("subject", ""),
        corpus_verdict=record.get("corpus_verdict") or VERDICT_SILENT,
        corpus_evidence=record.get("corpus_evidence", ""),
        accepted_at=record.get("accepted_at", ""),
        synced_at=record.get("synced_at"),
        synced_hash=record.get("synced_hash"),
    )


def load_judged_rule(rule_id: str) -> Optional[JudgedRule]:
    path = _path(BOOK_JUDGED, rule_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return _judged_from_dict(json.load(fh))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def iter_judged_rules() -> Iterator[JudgedRule]:
    """
    Every judged rule, newest acceptance first.

    Post: a file that cannot be read is skipped. This reader never returns a
          counted rule, and `iter_rules` never returns a judged one: the two
          books hold different evidence and a reader that mixed them would let
          a judgement read as a measurement (D16).
    """
    directory = book_dir(BOOK_JUDGED)
    if not os.path.isdir(directory):
        return
    records = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                records.append(_judged_from_dict(json.load(fh)))
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            continue
    records.sort(key=lambda r: r.accepted_at, reverse=True)
    yield from records


def judged_summary() -> dict:
    """Post: the judged book's size, and how the corpus reads it."""
    by_verdict = {verdict: 0 for verdict in VERDICTS}
    total = synced = 0
    for record in iter_judged_rules():
        by_verdict[record.corpus_verdict] = by_verdict.get(record.corpus_verdict, 0) + 1
        total += 1
        if record.synced_at:
            synced += 1
    return {"book": BOOK_JUDGED, "count": total, "verdicts": by_verdict,
            "synced": synced, "unsynced": total - synced}


def book_summary(book: str) -> dict:
    """
    Post: the counted book's size, its families, and how much of it the sheet
          has.

    Pre:  `book` is BOOK_COUNTED. `judged_summary` answers for the other one.

    A reader of the desk's rules panel needs the shape before the rules, and a
    count of what is unsynced is what says whether the sheet is behind.
    """
    by_family: dict = {}
    total = synced = changed = 0
    for record in iter_rules(book):
        by_family.setdefault(record.family, 0)
        by_family[record.family] += 1
        total += 1
        if record.synced_at:
            synced += 1
        if record.changed_since_sync:
            changed += 1
    return {"book": book, "count": total, "families": by_family,
            "synced": synced, "unsynced": total - synced,
            "changed_since_sync": changed}
