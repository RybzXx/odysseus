"""
services/offers/offer_thread.py

The conversation a sent offer answered, recovered from the offer itself.

Two methods, and they find different things (ws-03 D20).

Quoted history is the text. The customer's request survives inside the sent
reply that quoted it, and `parse_thread` pulls those turns out. This is the only
copy: INBOX is indexed from 2026-07-31 forward, while the corpus reaches back to
2024-08-25.

The `References` chain is the shape. It names every message in the thread,
including our own earlier offers, which the corpus already holds with their own
bodies. A named message the corpus holds becomes a turn with real text. A named
message it does not hold is not invented here.

Nothing in this module reads mail. It reads what `fetch_sent_threads` stored.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.constants import OFFER_CORPUS_DIR

from services.offers.models import SentOffer
from services.offers.offer_store import (
    load_offer,
    offer_dir,
    offers_of_message,
    stored_body,
)

# How a turn was recovered. Kept on every turn because the two carry different
# weight: a quoted turn is the words as sent, and a chain turn is another offer
# of ours that the headers place in the same thread.
TURN_QUOTE = "quote"
TURN_HEADER = "header"


@dataclass
class ThreadTurn:
    """One exchange in the conversation an offer answered."""
    source: str                     # TURN_QUOTE or TURN_HEADER
    level: int = 0                  # 0 is the offer's own prose; deeper is older
    body_html: str = ""
    attribution: str = ""           # "<sender> · <date>" where the quote names it
    message_id: str = ""            # filled for TURN_HEADER only
    subject: str = ""               # filled for TURN_HEADER only
    sent_at: Optional[datetime] = None


@dataclass
class OfferThread:
    """Everything recovered about one offer's conversation."""
    message_id: str
    attachment_name: str = ""
    body_captured: bool = False     # False when the walk never read this message
    turns: list = field(default_factory=list)
    chain_ids: list = field(default_factory=list)   # every id the headers name
    unresolved_ids: list = field(default_factory=list)  # named, not in the corpus

    @property
    def quote_turns(self) -> list:
        return [t for t in self.turns if t.source == TURN_QUOTE]

    @property
    def header_turns(self) -> list:
        return [t for t in self.turns if t.source == TURN_HEADER]

    @property
    def recovered(self) -> bool:
        """True when the thread yielded anything beyond the offer's own message."""
        return bool(self.header_turns) or len(self.quote_turns) > 1

    @property
    def first_contact(self) -> bool:
        """
        True when this offer opened the conversation rather than answering one.

        A first-contact offer quotes nothing and its headers name no earlier
        message, because there was none. Measured over the eight-month window:
        34 of 81 offers, whose subjects are Bil Weekend's own naming rather than
        a reply — "10 Days Tour in Iraq", "Adrian Meier - Iraq Tour Request".

        The distinction matters to a reader and to WP10. A first-contact offer
        is not a thread the walk failed to recover, and it carries no inbound
        request to read, so it cannot be graded against one.
        """
        return (self.body_captured and not self.recovered
                and not self.chain_ids and not self.unresolved_ids)


def _chain_of(offer: SentOffer) -> list:
    """
    Post: every message id the offer's headers name, oldest first, with no
          repeats and without the offer's own id.

    `References` is already oldest-first by convention, and `In-Reply-To` names
    the parent, which `References` normally ends with. Recording both and then
    de-duplicating covers the mailers that write only one of the two.
    """
    ordered, seen = [], set()
    for candidate in list(offer.references) + [offer.in_reply_to]:
        identifier = (candidate or "").strip()
        if not identifier or identifier == offer.message_id or identifier in seen:
            continue
        seen.add(identifier)
        ordered.append(identifier)
    return ordered


def _quote_turns(body_text: str, body_html: str) -> list:
    """
    Post: the quoted turns inside one sent body, newest first.

    `parse_thread` returns None when it finds no quoted material, which is a
    message that started a thread rather than one that failed to parse. Both
    give an empty list here, and `body_captured` is what tells them apart.
    """
    from src.email_thread_parser import parse_thread

    parsed = parse_thread(body_html or None, body_text or None)
    turns = []
    for turn in (parsed or []):
        turns.append(ThreadTurn(
            source=TURN_QUOTE,
            level=int(turn.get("level") or 0),
            body_html=turn.get("body_html") or "",
            attribution=turn.get("meta") or "",
        ))
    return turns


def _header_turns(chain_ids: list, own_message_id: str) -> tuple:
    """
    Post: (turns, unresolved). A named message the corpus holds becomes a turn
          carrying that offer's subject and sent date. One it does not hold is
          returned as unresolved rather than invented.

    A message can carry two offers, and both are the same message in the thread,
    so only the first is turned into a turn.
    """
    turns, unresolved = [], []
    for identifier in chain_ids:
        siblings = offers_of_message(identifier)
        if not siblings:
            unresolved.append(identifier)
            continue
        earlier = siblings[0]
        if earlier.message_id == own_message_id:
            continue
        turns.append(ThreadTurn(
            source=TURN_HEADER,
            message_id=earlier.message_id,
            subject=earlier.subject,
            sent_at=earlier.sent_at,
        ))
    return turns, unresolved


def thread_of(message_id: str, attachment_name: str = "") -> Optional[OfferThread]:
    """
    Recover one offer's conversation from what is stored beside it.

    Pre:  the corpus holds an offer for (message_id, attachment_name).
    Post: an OfferThread whose turns are marked by how each was found, or None
          when the corpus holds no such offer.

    Blame: an offer whose body was never captured returns `body_captured` False
    with whatever the headers give. A caller that reads that as "no thread"
    reports a walk that did not run as a thread that does not exist.
    """
    offer = load_offer(message_id, attachment_name)
    if offer is None:
        return None

    thread = OfferThread(
        message_id=offer.message_id,
        attachment_name=offer.attachment_name,
    )
    body = stored_body(offer_dir(offer.message_id, offer.attachment_name))
    if body is not None:
        thread.body_captured = True
        thread.turns.extend(_quote_turns(*body))

    thread.chain_ids = _chain_of(offer)
    header_turns, unresolved = _header_turns(thread.chain_ids, offer.message_id)
    thread.turns.extend(header_turns)
    thread.unresolved_ids = unresolved
    return thread


def _at_or_after(sent_at: Optional[datetime], since: datetime) -> bool:
    """
    Whether a stored send time falls on or after a cutoff.

    Every stored `sent_at` carries a timezone, because it comes from a Date
    header. A caller writing a cutoff by hand does not, and comparing the two
    raises. A naive cutoff is read as UTC, which is the only reading that needs
    no guess about where the caller stood.
    """
    if sent_at is None:
        return False
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    return sent_at >= since


def assemble_threads(since: Optional[datetime] = None) -> dict:
    """
    Recover every stored offer's thread, and report what did not recover.

    Pre:  nothing. An empty corpus gives zero counts. A naive `since` is read
          as UTC.
    Post: counts over the offers examined, and the attachment names of the ones
          whose thread did not recover.

    Blame: a report of successes with no denominator is the fault this
    workstream already made once, when 369 of 409 rejections stayed hidden. The
    failures are named, not counted alone.
    """
    from services.offers.offer_store import iter_offers

    outcome = {
        "examined": 0,
        "body_captured": 0,
        "with_quote_turns": 0,
        "with_header_turns": 0,
        "recovered": 0,
        "first_contact": 0,
        "not_recovered": [],
        "unresolved_ids": 0,
    }
    for offer in iter_offers():
        if since is not None and not _at_or_after(offer.sent_at, since):
            continue
        outcome["examined"] += 1
        thread = thread_of(offer.message_id, offer.attachment_name)
        if thread is None:
            outcome["not_recovered"].append(offer.attachment_name)
            continue
        if thread.body_captured:
            outcome["body_captured"] += 1
        if thread.quote_turns:
            outcome["with_quote_turns"] += 1
        if thread.header_turns:
            outcome["with_header_turns"] += 1
        outcome["unresolved_ids"] += len(thread.unresolved_ids)
        if thread.recovered:
            outcome["recovered"] += 1
        elif thread.first_contact:
            # It opened the conversation. There is no thread to recover, and
            # counting it as a failure would report a fault that is not one.
            outcome["first_contact"] += 1
        else:
            outcome["not_recovered"].append(
                f"{offer.attachment_name}"
                f"{'' if thread.body_captured else ' (body never captured)'}")
    return outcome


def corpus_has_bodies() -> bool:
    """True when at least one stored offer carries a captured body."""
    if not os.path.isdir(OFFER_CORPUS_DIR):
        return False
    for name in sorted(os.listdir(OFFER_CORPUS_DIR)):
        if stored_body(os.path.join(OFFER_CORPUS_DIR, name)) is not None:
            return True
    return False
