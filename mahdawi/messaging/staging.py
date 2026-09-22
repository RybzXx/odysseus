"""
messaging.staging — stage_change(). The only way an item reaches the owner.

A staged row is sufficient on its own: the payload carries the message, the
tier, Gemini's reading, the gate booleans, the draft, and any reply-check
problems.

  staged  — a draft exists and awaits approval.
  flagged — no draft. The gate stopped the item, or a layer failed.
"""
from __future__ import annotations

from typing import List, Optional

from mahdawi.messaging import store
from mahdawi.messaging.models import (
    AgentVerdict, Draft, GateFacts, InboundItem, STATE_FLAGGED, STATE_STAGED,
)


def stage_change(conn, item: InboundItem, reason: str, *,
                 tier: Optional[str] = None,
                 verdict: Optional[AgentVerdict] = None,
                 draft: Optional[Draft] = None,
                 facts: Optional[GateFacts] = None,
                 check_problems: Optional[List[str]] = None) -> str:
    """
    Pre : item was claimed and has no terminal state yet.
    Post: STATE_STAGED when a draft is attached, STATE_FLAGGED when not; the
          messages row carries that state and the reason.
    """
    payload = {
        "message": item.to_dict(),
        "tier": tier,
        "agent": verdict.to_dict() if verdict else None,
        "gate_facts": facts.to_dict() if facts else None,
        "draft": {"text": draft.text} if draft else None,
        "check_problems": list(check_problems or []),
    }
    store.insert_staged(conn, item.channel, item.external_id, payload, reason)
    state = STATE_STAGED if draft else STATE_FLAGGED
    store.resolve(conn, item.channel, item.external_id, state, reason)
    return state
