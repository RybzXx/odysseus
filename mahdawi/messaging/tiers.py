"""
messaging.tiers — code assigns the tier. Gemini only supplies a signal.

The result is the more restrictive of Gemini's tier_signal and a floor code
computes from the gate facts and the confidence. Gemini can raise an item (FAQ
to ESCALATE), because raising makes the max more restrictive. It cannot lower
one into auto-send. No prompt wording changes this.
"""
from __future__ import annotations

from mahdawi.messaging import settings
from mahdawi.messaging.models import (
    AgentVerdict, GateFacts, INTENT_FLOOR, TIER_ESCALATE, TIER_RANK,
)


def code_floor(verdict: AgentVerdict, facts: GateFacts) -> str:
    """
    Post: ESCALATE whenever confidence is short of the threshold, the sender is
          repeating an unresolved thread, the tone reads negative, or the
          intent is unknown. Otherwise the intent's own floor (INTENT_FLOOR), so
          an FAQ signal on a complaint or an order cannot reach auto-send.
    """
    if verdict.confidence < settings.CONFIDENCE_THRESHOLD:
        return TIER_ESCALATE
    if facts.is_repeat:
        return TIER_ESCALATE
    if verdict.tone == "negative":
        return TIER_ESCALATE
    return INTENT_FLOOR.get(verdict.intent, TIER_ESCALATE)


def assign(verdict: AgentVerdict, facts: GateFacts) -> str:
    """
    Pre : verdict came from a Classifier.
    Post: the tier is at least as restrictive as code_floor(), unless
          ALLOW_DOWNWARD_OVERRIDE is set.
    Invariant: never FAQ for a verdict whose confidence is below the threshold.
    """
    if verdict.tier_signal not in TIER_RANK:
        return TIER_ESCALATE
    if settings.ALLOW_DOWNWARD_OVERRIDE:
        return verdict.tier_signal
    floor = code_floor(verdict, facts)
    return max((verdict.tier_signal, floor), key=TIER_RANK.index)


def reason_for(tier: str, verdict: AgentVerdict, facts: GateFacts) -> str:
    """Plain-language account of why the tier landed where it did, for the audit."""
    if tier == verdict.tier_signal:
        return "agent signal %s; %s" % (tier, verdict.reasoning)
    bits = []
    if verdict.confidence < settings.CONFIDENCE_THRESHOLD:
        bits.append("confidence %.2f below %.2f" % (verdict.confidence,
                                                    settings.CONFIDENCE_THRESHOLD))
    if facts.is_repeat:
        bits.append("repeat on an unresolved thread")
    if verdict.tone == "negative":
        bits.append("negative tone")
    floor = INTENT_FLOOR.get(verdict.intent, TIER_ESCALATE)
    if TIER_RANK.index(floor) > TIER_RANK.index(verdict.tier_signal):
        bits.append("intent %r is at least %s" % (verdict.intent, floor))
    return "code raised %s to %s: %s" % (verdict.tier_signal, tier, "; ".join(bits))
