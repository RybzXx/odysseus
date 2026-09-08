"""What categorisation state one email is in.

The calibration studio used to show two unrelated answers to "is this
categorised": the category a pass proposed, and whether any rule matched. They
could disagree, and nothing on the page said which was which. One derived state
replaces both.

State is never stored. It falls out of the rules, the human's overrides and the
review pass's verdicts, so it cannot go stale against them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from services.organisers.match_detail import STRONG, WEAK, EmailText, evaluate_rules

# An organiser holds this email on a sender or domain rule, or by human decree.
ASSIGNED = "assigned"
# An organiser holds it, but only because a keyword appeared in the text.
WEAK_MATCH = "weak"
# Nothing holds it, and the review pass has not looked at it yet.
PENDING = "pending"
# Nothing holds it, and the review pass looked and named no category.
DECLINED = "declined"

CATEGORISED_STATES = (ASSIGNED, WEAK_MATCH)


@dataclass
class EmailState:
    """One email's categorisation, and what produced it."""

    state: str
    organiser_ids: List[str]
    # The strongest evidence any holding organiser has, for showing the user
    # why a weak match is weak.
    evidence: Dict[str, Any]


def _parsed_organisers(organisers: Iterable[Any]) -> List[Tuple[Any, Dict, List]]:
    parsed = []
    for org in organisers:
        try:
            parsed.append((
                org,
                json.loads(org.rules_json or "{}"),
                json.loads(org.target_accounts or "[]"),
            ))
        except (TypeError, ValueError):
            # A malformed organiser holds nothing.
            continue
    return parsed


def derive_states(
    emails: List[Dict[str, Any]],
    organisers: Iterable[Any],
    overrides: Dict[Tuple[str, str], Dict[str, Any]],
    reviewed_keys: Optional[Iterable[Tuple[str, str]]] = None,
) -> Dict[Tuple[str, str], EmailState]:
    """Resolve every email to exactly one state.

    Pre:  overrides is the map from load_organiser_overrides; reviewed_keys
          names the messages the review pass has already judged.
    Post: {(account_key, uid): EmailState} covering every input email once.
    Inv:  the four states partition the corpus -- no email lands in two, and
          none lands in none. `assigned` and `weak` are the categorised pair;
          `pending` and `declined` are the uncategorised pair, and the only
          difference between them is whether anything has looked yet.
    """
    parsed = _parsed_organisers(organisers)
    reviewed = set(reviewed_keys or ())
    states: Dict[Tuple[str, str], EmailState] = {}

    for email in emails:
        key = (
            str(email.get("account_key") or email.get("account_id") or ""),
            str(email.get("uid") or ""),
        )
        entry = overrides.get(key) or {}
        assigned_to = entry.get("assigned")
        excluded = entry.get("excluded", ())

        # A human assignment settles it outright, the same precedence
        # email_belongs_to_organiser applies.
        if assigned_to:
            states[key] = EmailState(ASSIGNED, [assigned_to], {"source": "human"})
            continue

        holders: List[str] = []
        best = "none"
        evidence: Dict[str, Any] = {}
        text = EmailText.of(email)
        for org, rules, accounts in parsed:
            if org.id in excluded:
                continue
            match = evaluate_rules(email, accounts, rules, text)
            if not match.matched:
                continue
            holders.append(org.id)
            if match.strength == STRONG:
                best = STRONG
                evidence = {
                    "source": "rule",
                    "senders": match.sender_hits,
                    "domains": match.domain_hits,
                }
            elif best != STRONG:
                best = WEAK
                evidence = {"source": "rule", "keywords": match.keyword_hits}

        if best == STRONG:
            states[key] = EmailState(ASSIGNED, holders, evidence)
        elif best == WEAK:
            states[key] = EmailState(WEAK_MATCH, holders, evidence)
        elif key in reviewed:
            states[key] = EmailState(DECLINED, [], {"source": "review"})
        else:
            states[key] = EmailState(PENDING, [], {})

    return states


def count_states(states: Dict[Tuple[str, str], EmailState]) -> Dict[str, int]:
    """Tally the corpus by state.

    Post: a count per state plus the two roll-ups the studio shows.
    Inv:  ``categorised + uncategorised == total``, which is what made the old
          pair of counts contradict each other.
    """
    tally = {ASSIGNED: 0, WEAK_MATCH: 0, PENDING: 0, DECLINED: 0}
    for entry in states.values():
        tally[entry.state] += 1

    categorised = tally[ASSIGNED] + tally[WEAK_MATCH]
    uncategorised = tally[PENDING] + tally[DECLINED]
    return {
        **tally,
        "categorised": categorised,
        "uncategorised": uncategorised,
        "total": categorised + uncategorised,
    }
