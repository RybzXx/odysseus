"""
messaging.dispatch — the one place a send can happen.

Grep for channel.send outside this module. There must be no hit.

Six conditions must all hold for text to reach a customer, checked together
immediately before the call:

  1. the channel can send at all
  2. code assigned the FAQ tier (routine)
  3. the owner switched auto-send on (settings.AUTOSEND)
  4. the reply passes reply_check: only shop-supplied numbers, no banned or
     promise terms, Arabic, short, no emoji or hashtags
  5. the text fits the channel's byte limit
  6. the gate passes, re-checked now (a reply window can close mid-run)

Anything else stages. Failure of any kind stages. No path turns an error into a send.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from mahdawi.messaging import gate, reply_check, settings, store
from mahdawi.messaging.channels import ChannelUnavailable
from mahdawi.messaging.models import (
    AgentVerdict, BLOCK_PATH_UNAVAILABLE, BLOCK_TOO_LONG, Draft, GateFacts,
    InboundItem, STAGE_AUTOSEND_OFF, STAGE_CHANNEL_READ_ONLY, STAGE_REPLY_CHECK_FAILED,
    STAGE_TIER_REQUIRES_APPROVAL, STATE_AUTO_REPLIED, ShopFacts, TIER_FAQ,
)
from mahdawi.messaging.staging import stage_change


def sendable(conn, channel, item: InboundItem, tier: str, draft: Draft,
             shop: ShopFacts) -> Tuple[bool, Optional[str], List[str]]:
    """
    The truth table, as one function. Returns (ok, reason, check_problems).

    Pre : the item has passed the gate once already.
    Post: a False answer always names the reason the staged row records.
    """
    caps = channel.capabilities()
    if not caps.can_send:
        return False, STAGE_CHANNEL_READ_ONLY, []
    if tier != TIER_FAQ:
        return False, STAGE_TIER_REQUIRES_APPROVAL, []
    found = reply_check.problems(draft.text, shop, item.text)
    if not settings.AUTOSEND:
        return False, STAGE_AUTOSEND_OFF, found
    if found:
        return False, STAGE_REPLY_CHECK_FAILED, found
    if len(draft.text.encode("utf-8")) > caps.text_byte_limit:
        return False, BLOCK_TOO_LONG, []
    recheck = gate.evaluate(conn, item, caps)
    if not recheck.passed:
        return False, recheck.blocked_reason, []
    return True, None, []


def dispatch(conn, channel, item: InboundItem, tier: str, draft: Draft,
             verdict: AgentVerdict, facts: GateFacts, shop: ShopFacts):
    """
    Send or stage. Returns (terminal_state, reason).

    Pre : item is claimed and unresolved.
    Post: exactly one terminal state is written; a send happened only when
          sendable() returned True.
    Invariant: on a send, store.record_reply runs in the same call.
    """
    ok, reason, found = sendable(conn, channel, item, tier, draft, shop)
    if not ok:
        return stage_change(conn, item, reason, tier=tier, verdict=verdict, draft=draft,
                            facts=facts, check_problems=found), reason
    try:
        channel.send(item.thread_ref, draft.text)
    except ChannelUnavailable:
        return stage_change(conn, item, BLOCK_PATH_UNAVAILABLE, tier=tier, verdict=verdict,
                            draft=draft, facts=facts), BLOCK_PATH_UNAVAILABLE
    store.record_reply(conn, item.channel, item.thread_ref, item.external_id, item.kind)
    store.resolve(conn, item.channel, item.external_id, STATE_AUTO_REPLIED, reason=None)
    return STATE_AUTO_REPLIED, None
