"""
messaging.agents — the two Layer Two seams the runner calls.

Classifier reads a message; ReplyWriter writes the answer. layer2.replies
implements both with Gemini, and tests inject fakes. Neither has any authority
over the tier or the send: tiers.assign and dispatch.sendable hold that.
"""
from __future__ import annotations

from typing import Protocol

from mahdawi.messaging.models import AgentVerdict, InboundItem, ShopFacts


class Classifier(Protocol):
    def classify(self, payload: dict) -> AgentVerdict:
        """
        Pre : payload came from gate.agent_payload — booleans, never clocks.
        Post: tier_signal is in TIER_RANK; confidence is in [0.0, 1.0].
        Raises: anything. The runner flags the item AGENT_UNAVAILABLE.
        """


class ReplyWriter(Protocol):
    def write(self, item: InboundItem, verdict: AgentVerdict, facts: ShopFacts) -> str:
        """
        Post: reply text that uses only ShopFacts.
        Raises: anything. The runner flags the item AGENT_UNAVAILABLE.
        """
