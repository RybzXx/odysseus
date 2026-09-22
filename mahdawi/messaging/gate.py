"""
messaging.gate — deterministic pre-checks. Gemini is not consulted here.

Every check reads a clock, a counter, or a ledger. None reads the message text.
This module produces GateFacts, and GateFacts is the entire view of time and
history Gemini ever receives.

The first failing check terminates the item, so a message past its reply
window never costs a Gemini call. Duplicate detection is store.claim(), an
atomic INSERT, not a check here.
"""
from __future__ import annotations

from mahdawi.messaging import settings, store
from mahdawi.messaging.models import (
    BLOCK_CAP_REACHED, BLOCK_COMMENT_REPLY_USED, BLOCK_EXPIRED_WINDOW,
    BLOCK_REPEAT_UNRESOLVED, Capabilities, GateFacts, GateResult, InboundItem,
    KIND_COMMENT, utcnow,
)


def window_seconds(item: InboundItem, caps: Capabilities) -> int:
    """A DM uses the channel's reply window; a private reply to a comment gets 7 days."""
    if item.kind == KIND_COMMENT:
        return settings.COMMENT_REPLY_WINDOW_SECONDS
    return caps.reply_window_seconds


def evaluate(conn, item: InboundItem, caps: Capabilities) -> GateResult:
    """
    Pre : item was claimed; caps came from the channel that produced item.
    Post: facts is fully populated whether or not the item is blocked.
    Invariant: performs no send and mutates nothing.
    """
    age = (utcnow() - item.created_at).total_seconds()
    window_open = age < window_seconds(item, caps)
    cap_available = (store.replies_in_window(conn, item.channel, item.thread_ref, hours=24)
                     < settings.DAILY_REPLY_CAP)
    is_repeat = store.has_unresolved_prior(conn, item.channel, item.thread_ref)
    reply_used = (item.kind == KIND_COMMENT
                  and store.comment_reply_used(conn, item.channel, item.external_id))

    facts = GateFacts(window_open=window_open, cap_available=cap_available,
                      is_repeat=is_repeat, comment_reply_used=reply_used,
                      channel_can_send=caps.can_send)

    if not window_open:
        return GateResult(facts, BLOCK_EXPIRED_WINDOW)
    if reply_used:
        return GateResult(facts, BLOCK_COMMENT_REPLY_USED)
    if is_repeat:
        return GateResult(facts, BLOCK_REPEAT_UNRESOLVED)
    if not cap_available:
        return GateResult(facts, BLOCK_CAP_REACHED)
    return GateResult(facts, None)


def agent_payload(item: InboundItem, facts: GateFacts) -> dict:
    """
    The exact object Gemini sees. Nothing else may be added.

    Invariant: no key holds a timestamp, a count, or an identifier.
    """
    return {"text": item.text, "kind": item.kind, "facts": facts.to_dict()}
