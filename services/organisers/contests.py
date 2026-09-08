"""Raising and resolving contests over an organiser's claim on an email.

A contest asks a human to judge one categorisation. Raising one changes no
membership; resolving one either leaves the rules alone (confirm) or writes an
ordinary exclusion override (reject). Membership therefore stays the answer of
``email_belongs_to_organiser`` alone.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.database import (
    CategorisationContest,
    EmailOrganiserOverride,
    utcnow_naive,
)
from services.organisers.match_detail import EmailText, RuleMatch, evaluate_rules

OPEN = "open"
CONFIRMED = "confirmed"
REJECTED = "rejected"

SOURCE_RULE_WEAK = "rule_weak"
SOURCE_REVIEW = "llm"

# Which way the claim runs. The rules already place an asserted match; nothing
# places a proposed one until a human confirms it.
ASSERTED = "asserted"
PROPOSED = "proposed"

# The verdicts a human may return. Exported so a caller can check one before
# it has a contest to apply it to.
VERDICTS = frozenset({CONFIRMED, REJECTED})

_RESOLUTIONS = VERDICTS


def _message_key(row) -> Tuple[str, str]:
    return (row.account_key or "", row.uid or "")


def _text_for(email: Dict[str, Any], cache: Dict[int, EmailText]) -> EmailText:
    """The lowered text for this email, built once per scan.

    Keyed on identity rather than content: the caller passes the same dict
    objects on every round, and an email carries no stable hashable key.
    """
    key = id(email)
    text = cache.get(key)
    if text is None:
        text = EmailText.of(email)
        cache[key] = text
    return text


def load_contests(
    db: Session,
    owner: Optional[str],
    *,
    state: Optional[str] = OPEN,
) -> Dict[Tuple[str, str], List[CategorisationContest]]:
    """Every contest this owner holds, indexed by message.

    Pre:  db is an open session.
    Post: {(account_key, uid): [contest, ...]}, one list per message. Loaded
          once per request rather than queried per email, matching how
          load_organiser_overrides is used against the same corpus.
    """
    by_message: Dict[Tuple[str, str], List[CategorisationContest]] = {}
    try:
        query = db.query(CategorisationContest).filter(
            or_(CategorisationContest.owner == owner, CategorisationContest.owner == None),
        )
        if state:
            query = query.filter(CategorisationContest.state == state)
        rows = query.all()
    except Exception:
        # The table postdates some databases; absent it, nothing is contested.
        return by_message

    for row in rows:
        by_message.setdefault(_message_key(row), []).append(row)
    return by_message


def _evidence(match: RuleMatch) -> Dict[str, Any]:
    return {
        "strength": match.strength,
        "senders": match.sender_hits,
        "domains": match.domain_hits,
        "keywords": match.keyword_hits,
    }


def _weak_match_reason(match: RuleMatch) -> str:
    hits = ", ".join(f"'{k}'" for k in match.keyword_hits)
    if len(match.keyword_hits) == 1:
        return f"Matched on the keyword {hits} alone, with no sender or domain rule."
    return f"Matched on keywords {hits} only, with no sender or domain rule."


def raise_weak_match_contests(
    db: Session,
    owner: Optional[str],
    weak_matches: Iterable[Tuple[Dict[str, Any], str, RuleMatch]],
) -> int:
    """Open a contest for each weak claim that has no verdict yet.

    Pre:  every tuple is (email, organiser_id, match) where match.is_weak.
    Post: an open contest exists for each such claim not already recorded;
          returns how many were newly opened. A claim already confirmed or
          rejected is left alone, so a human verdict is never re-asked.
    Inv:  the caller's rules are untouched. Raising a contest does not move an
          email between organisers.
    """
    existing = {
        (c.account_key or "", c.uid or "", c.organiser_id)
        for contests in load_contests(db, owner, state=None).values()
        for c in contests
    }

    opened = 0
    for email, organiser_id, match in weak_matches:
        if not match.is_weak:
            continue
        account_key = str(email.get("account_key") or "")
        uid = str(email.get("uid") or "")
        if not uid or (account_key, uid, organiser_id) in existing:
            continue

        db.add(CategorisationContest(
            id=uuid.uuid4().hex,
            owner=owner,
            account_key=account_key,
            uid=uid,
            organiser_id=organiser_id,
            source=SOURCE_RULE_WEAK,
            evidence_json=json.dumps(_evidence(match), ensure_ascii=False),
            reason=_weak_match_reason(match),
            state=OPEN,
        ))
        existing.add((account_key, uid, organiser_id))
        opened += 1

    if opened:
        db.commit()
    return opened


def scan_weak_matches(
    db: Session,
    owner: Optional[str],
    emails: List[Dict[str, Any]],
    organisers: Iterable[Any],
    overrides: Dict[Tuple[str, str], Dict[str, Any]],
) -> int:
    """Contest every weak claim in the corpus that no human has judged.

    Pre:  organisers carry rules_json and target_accounts as stored;
          overrides is the map from load_organiser_overrides.
    Post: an open contest exists for each unjudged weak match; returns how
          many were newly opened.
    Inv:  a message the human has already assigned or excluded is skipped. The
          point of a contest is to ask an open question, and that one is shut.
    """
    weak: List[Tuple[Dict[str, Any], str, RuleMatch]] = []
    # Lowered once per email and shared across every organiser: the loop below
    # is corpus times taxonomy, and the text does not change between rounds.
    texts: Dict[int, EmailText] = {}

    for org in organisers:
        try:
            rules = json.loads(org.rules_json or "{}")
            accounts = json.loads(org.target_accounts or "[]")
        except (TypeError, ValueError):
            # A malformed organiser cannot make a claim worth contesting.
            continue

        for email in emails:
            entry = overrides.get((
                str(email.get("account_key") or email.get("account_id") or ""),
                str(email.get("uid") or ""),
            ))
            if entry and (entry.get("assigned") or org.id in entry.get("excluded", ())):
                continue

            match = evaluate_rules(email, accounts, rules, _text_for(email, texts))
            if match.is_weak:
                weak.append((email, org.id, match))

    return raise_weak_match_contests(db, owner, weak)


def resolve_contest(
    db: Session,
    owner: Optional[str],
    contest_id: str,
    verdict: str,
) -> CategorisationContest:
    """Record a human verdict on one contest.

    Pre:  verdict is "confirmed" or "rejected"; contest_id belongs to owner.
    Post: the contest carries the verdict and a resolution time, and membership
          matches what the human just said.
    Inv:  a verdict writes an override only where the rules would otherwise
          disagree with it. The four cases:

            asserted + confirmed -> nothing; the rules already say this, and a
              second record would outlive the rule it agreed with.
            asserted + rejected  -> an exclusion, which is what removes the
              email from an organiser whose rule keeps claiming it.
            proposed + confirmed -> an assignment, because no rule places this
              email and only the override will.
            proposed + rejected  -> nothing; nothing placed it to begin with.

    Raises LookupError when the contest is absent or not this owner's, and
    ValueError on an unknown verdict -- both caller bugs.
    """
    if verdict not in _RESOLUTIONS:
        raise ValueError(f"unknown verdict: {verdict!r}")

    contest = db.query(CategorisationContest).filter(
        CategorisationContest.id == contest_id,
        or_(CategorisationContest.owner == owner, CategorisationContest.owner == None),
    ).first()
    if contest is None:
        raise LookupError(contest_id)

    contest.state = verdict
    contest.resolved_at = utcnow_naive()

    claim = (contest.claim or ASSERTED)
    if claim == ASSERTED and verdict == REJECTED:
        _exclude(db, owner, contest)
    elif claim == PROPOSED and verdict == CONFIRMED:
        _assign(db, owner, contest)

    db.commit()
    return contest


def _assign(db: Session, owner: Optional[str], contest: CategorisationContest) -> None:
    """Write the assignment override a confirmed proposal means.

    Pre:  the contest is a proposed claim the human has just confirmed.
    Post: exactly one assignment stands for this message. An assignment is
          singular by construction -- an email belongs to one organiser by
          human decree -- so an earlier one is replaced, not added to.
    """
    existing = db.query(EmailOrganiserOverride).filter(
        EmailOrganiserOverride.owner == owner,
        EmailOrganiserOverride.account_key == contest.account_key,
        EmailOrganiserOverride.uid == contest.uid,
        EmailOrganiserOverride.excluded_from_id == None,
    ).first()
    if existing:
        existing.organiser_id = contest.organiser_id
        return

    db.add(EmailOrganiserOverride(
        id=uuid.uuid4().hex,
        owner=owner,
        account_key=contest.account_key,
        uid=contest.uid,
        organiser_id=contest.organiser_id,
        excluded_from_id=None,
    ))


def _exclude(db: Session, owner: Optional[str], contest: CategorisationContest) -> None:
    """Write the exclusion override a rejection means, unless it already exists."""
    already = db.query(EmailOrganiserOverride).filter(
        EmailOrganiserOverride.owner == owner,
        EmailOrganiserOverride.account_key == contest.account_key,
        EmailOrganiserOverride.uid == contest.uid,
        EmailOrganiserOverride.excluded_from_id == contest.organiser_id,
    ).first()
    if already:
        return

    db.add(EmailOrganiserOverride(
        id=uuid.uuid4().hex,
        owner=owner,
        account_key=contest.account_key,
        uid=contest.uid,
        organiser_id=None,
        excluded_from_id=contest.organiser_id,
    ))


def reopen_contests_for_organiser(db: Session, owner: Optional[str], organiser_id: str) -> int:
    """Discard resolved contests for one organiser after its rules change.

    Pre:  organiser_id names an organiser whose rules were just edited.
    Post: its confirmed contests are deleted, so the next scan judges the new
          rules rather than inheriting a verdict about the old ones; returns
          how many were discarded.
    Inv:  rejections survive. A rejection wrote an exclusion override, and that
          override is the durable record -- deleting the contest behind it
          would invite the same question again while the answer still stands.
    """
    rows = db.query(CategorisationContest).filter(
        or_(CategorisationContest.owner == owner, CategorisationContest.owner == None),
        CategorisationContest.organiser_id == organiser_id,
        CategorisationContest.state == CONFIRMED,
    ).all()
    for row in rows:
        db.delete(row)
    if rows:
        db.commit()
    return len(rows)
