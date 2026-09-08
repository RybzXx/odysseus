"""Rule evaluation that reports *why* an email matched, not merely whether.

``_matches_rule`` in the router answers a yes/no question, which is all the
membership decision needs. Contesting a decision needs more: a match resting on
one keyword found in a subject line is a far weaker claim than a match on the
sender's domain, and only the second is worth trusting unreviewed.

This module carries the single evaluation, and the router's boolean delegates to
it, so the two can never drift into answering the same question differently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Folder prefixes that mark a message the user sent rather than received.
# Kept here beside the only code that reads them.
_SENT_FOLDER_PREFIXES = ("sent", "inbox/sent", "[gmail]/sent")

STRONG = "strong"
WEAK = "weak"
NONE = "none"


@dataclass
class RuleMatch:
    """Evidence for one organiser's claim on one email.

    Inv: ``matched`` is True iff at least one of the hit lists is non-empty or
         ``account_only`` is set. ``strength`` is NONE iff ``matched`` is False.
    """

    matched: bool = False
    strength: str = NONE
    sender_hits: List[str] = field(default_factory=list)
    domain_hits: List[str] = field(default_factory=list)
    keyword_hits: List[str] = field(default_factory=list)
    # The organiser targets this email's account and declares no rules, so the
    # account alone carries the claim. Deliberate targeting, not a loose match.
    account_only: bool = False

    @property
    def is_weak(self) -> bool:
        return self.strength == WEAK


def _is_outbound(email: Dict[str, Any]) -> bool:
    return str(email.get("folder") or "").lower().startswith(_SENT_FOLDER_PREFIXES)


@dataclass
class EmailText:
    """One email's searchable text, lowered once.

    A scan evaluates every email against every organiser, so lowering the same
    subject and snippet inside each rule check repeated the work once per
    category. Building this once per email and reusing it makes the cost linear
    in the corpus rather than in corpus times taxonomy.
    """

    from_name: str
    from_address: str
    subject: str
    snippet: str
    recipients: str

    @classmethod
    def of(cls, email: Dict[str, Any]) -> "EmailText":
        # Recipients count only for mail the user sent. On a received message
        # the sender is the correspondent and the recipient is the user, so
        # matching recipients there would make a rule naming someone also claim
        # every message addressed to them.
        recipients = ""
        if _is_outbound(email):
            recipients = f"{email.get('to_text') or ''} {email.get('cc_text') or ''}".lower()
        return cls(
            from_name=(email.get("from_name") or "").lower(),
            from_address=(email.get("from_address") or "").lower(),
            subject=(email.get("subject") or "").lower(),
            snippet=(email.get("snippet") or "").lower(),
            recipients=recipients,
        )


def evaluate_rules(
    email: Dict[str, Any],
    target_accounts: List[str],
    rules: Dict[str, Any],
    text: Optional["EmailText"] = None,
) -> RuleMatch:
    """Evaluate one organiser's account filter and rules against one email.

    Pre:  ``rules`` and ``target_accounts`` come from the same organiser;
          ``email`` carries the keys the email index produces. ``text``, when
          given, must be EmailText.of(email) -- passing another email's text
          is a caller bug that silently matches the wrong message.
    Post: a RuleMatch whose ``matched`` equals what a plain boolean matcher
          would return for these inputs, plus the tokens that fired.
    Inv:  every rule that fires appears in a hit list. Unlike the boolean
          matcher this does not stop at the first hit, because a contest needs
          the whole picture to be judged.
    """
    senders = [s.strip().lower() for s in rules.get("senders", []) if s.strip()]
    keywords = [k.strip().lower() for k in rules.get("keywords", []) if k.strip()]
    domains = [d.strip().lower().lstrip("@") for d in rules.get("domains", []) if d.strip()]

    # An organiser with no criteria at all matches nothing. It is unconfigured,
    # not universal.
    if not target_accounts and not senders and not keywords and not domains:
        return RuleMatch()

    if target_accounts:
        acc_id = email.get("account_key") or email.get("account_id") or ""
        if acc_id not in target_accounts:
            return RuleMatch()

    # Account match alone is sufficient when the organiser declares no rules.
    if not senders and not keywords and not domains:
        return RuleMatch(matched=True, strength=STRONG, account_only=True)

    text = text or EmailText.of(email)
    from_name = text.from_name
    from_addr = text.from_address
    subject = text.subject
    body_snippet = text.snippet
    recipients = text.recipients

    sender_hits = [
        s for s in senders
        if s in from_name or s in from_addr or (recipients and s in recipients)
    ]
    domain_hits = [
        d for d in domains
        if f"@{d}" in from_addr
        or from_addr.endswith(f".{d}")
        or (recipients and f"@{d}" in recipients)
    ]
    keyword_hits = [k for k in keywords if k in subject or k in body_snippet]

    if sender_hits or domain_hits:
        strength = STRONG
    elif keyword_hits:
        strength = WEAK
    else:
        return RuleMatch()

    return RuleMatch(
        matched=True,
        strength=strength,
        sender_hits=sender_hits,
        domain_hits=domain_hits,
        keyword_hits=keyword_hits,
    )
