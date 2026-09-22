"""
messaging.models — the objects that cross a layer boundary.

Capabilities  : what one channel can actually do. The gate reads limits here.
InboundItem   : a DM or a comment, normalized. The only shape the core knows.
GateFacts     : the deterministic booleans — the WHOLE of what Gemini is told
                about time, counts, and history.
AgentVerdict  : Gemini's reading of the message. Carries no tier; code assigns it.
ShopFacts     : the facts a reply may state, and so the numbers it may contain.
Draft         : the reply text Gemini wrote.

Terminal states are exhaustive and mutually exclusive: every ingested item ends
as exactly one of TERMINAL_STATES.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional, Tuple

from mahdawi.content import text_check


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})


def _title_words(text: str):
    """Words of 3+ letters, Arabic variants folded, the article ال dropped."""
    for w in re.findall(r"\w+", (text or "").translate(_FOLD).lower()):
        if w.startswith("ال") and len(w) > 4:
            w = w[2:]
        if len(w) >= 3 and not w.isdigit():
            yield w


# -- vocabulary ----------------------------------------------------------------
KIND_DM = "dm"
KIND_COMMENT = "comment"

TIER_FAQ = "FAQ_TIER"
TIER_TRANSACTION = "TRANSACTION_TIER"
TIER_ESCALATE = "ESCALATE_TIER"
# Ordered least-to-most restrictive. An agent may move an item up, never down.
TIER_RANK = [TIER_FAQ, TIER_TRANSACTION, TIER_ESCALATE]

# Intent vocabulary. Code owns it, and each intent carries the least
# restrictive tier it may land in, whatever tier Gemini signals with it.
INTENT_FLOOR = {
    "greeting": TIER_FAQ,
    "price": TIER_FAQ,
    "availability": TIER_FAQ,
    "shipping": TIER_FAQ,
    "how_to_order": TIER_FAQ,
    "order": TIER_TRANSACTION,
    "negotiation": TIER_TRANSACTION,
    "complaint": TIER_ESCALATE,
    "return": TIER_ESCALATE,
    "other": TIER_ESCALATE,
}
INTENTS = tuple(INTENT_FLOOR)

STATE_AUTO_REPLIED = "auto_replied"
STATE_STAGED = "staged"                    # a draft awaits the owner's approval
STATE_FLAGGED = "flagged"                  # recorded for review, no draft
STATE_SKIPPED_DUPLICATE = "skipped_duplicate"
TERMINAL_STATES = (STATE_AUTO_REPLIED, STATE_STAGED, STATE_FLAGGED, STATE_SKIPPED_DUPLICATE)

# -- gate block reasons (code-owned) -------------------------------------------
BLOCK_DUPLICATE = "DUPLICATE"
BLOCK_EXPIRED_WINDOW = "EXPIRED_WINDOW"
BLOCK_CAP_REACHED = "CAP_REACHED"
BLOCK_REPEAT_UNRESOLVED = "REPEAT_UNRESOLVED"
BLOCK_COMMENT_REPLY_USED = "COMMENT_REPLY_USED"
BLOCK_PATH_UNAVAILABLE = "PATH_UNAVAILABLE"
BLOCK_TOO_LONG = "TOO_LONG"
BLOCK_AGENT_UNAVAILABLE = "AGENT_UNAVAILABLE"

# -- why a draft went to the owner rather than to a customer --------------------
STAGE_TIER_REQUIRES_APPROVAL = "TIER_REQUIRES_APPROVAL"
STAGE_AUTOSEND_OFF = "AUTOSEND_OFF"
STAGE_REPLY_CHECK_FAILED = "REPLY_CHECK_FAILED"
STAGE_CHANNEL_READ_ONLY = "CHANNEL_READ_ONLY"


@dataclass(frozen=True)
class Capabilities:
    """What a channel can do. Immutable for the run."""
    name: str
    can_send: bool
    reply_window_seconds: int
    supports_comment_reply: bool
    text_byte_limit: int


@dataclass
class InboundItem:
    channel: str
    external_id: str          # unique within channel; the ledger key
    thread_ref: str           # OPAQUE to core. The adapter alone knows its shape.
    kind: str                 # KIND_DM | KIND_COMMENT
    text: str
    author_ref: str
    created_at: datetime      # tz-aware UTC; the window clock reads this

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d


@dataclass(frozen=True)
class GateFacts:
    """Invariant: booleans only. A timestamp or a count reaching Gemini is a leak."""
    window_open: bool
    cap_available: bool
    is_repeat: bool
    comment_reply_used: bool
    channel_can_send: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateResult:
    facts: GateFacts
    blocked_reason: Optional[str] = None   # None = the item may proceed

    @property
    def passed(self) -> bool:
        return self.blocked_reason is None


@dataclass
class AgentVerdict:
    """
    Gemini's reading. Deliberately has no tier field.

    Post: confidence is in [0.0, 1.0]; tier_signal is one of TIER_RANK.
    """
    intent: str
    tier_signal: str
    tone: str
    confidence: float
    reasoning: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ShopFacts:
    """
    Everything a reply may state. Built by code from the store settings and the
    products already approved or posted.

    Invariant: allowed_numbers() is the complete set of numbers a reply may
    contain; the reply check refuses any other number.
    """
    lines: Tuple[Tuple[str, str], ...] = ()          # (name, text), e.g. ("delivery", "...")
    products: Tuple[Tuple[str, int], ...] = ()       # (title, price in IQD)

    def named_in(self, message: str) -> Tuple[Tuple[str, int], ...]:
        """
        Post: the products whose title shares a word of 3+ letters with message,
              after Arabic spelling variants (أ/إ/آ, ة/ه, ى/ي) are folded.
        """
        words = set(_title_words(message))
        return tuple(p for p in self.products if words & set(_title_words(p[0])))

    def allowed_numbers(self, message: Optional[str] = None) -> set:
        """
        Post: shop-line numbers plus product numbers. With message, only the
              products the message names contribute, so a reply cannot quote
              another product's price.
        """
        products = self.products if message is None else self.named_in(message)
        nums = {price for _, price in products if price}
        for _, text in self.lines:
            nums.update(text_check.numbers_in(text))
        for title, _ in products:
            nums.update(text_check.numbers_in(title))
        return nums

    def to_prompt(self) -> dict:
        return {"shop": dict(self.lines),
                "products": [{"title": t, "price_iqd": p} for t, p in self.products]}


@dataclass
class Draft:
    text: str


@dataclass
class RunReport:
    """The four terminal counts must partition the ingested items."""
    ingested: int = 0
    classified: int = 0
    per_tier: dict = field(default_factory=dict)
    auto_replied: int = 0
    staged: int = 0
    flagged: int = 0
    skipped_duplicate: int = 0
    flags: list = field(default_factory=list)   # [(external_id, reason)]

    def terminal_total(self) -> int:
        return self.auto_replied + self.staged + self.flagged + self.skipped_duplicate

    def balanced(self) -> bool:
        return self.ingested == self.terminal_total()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["terminal_total"] = self.terminal_total()
        d["balanced"] = self.balanced()
        return d
