"""
messaging.channels — the adapter contract. Three methods, no more.

Core never imports a concrete channel; the runner receives one. The adapter
owns identifier translation: core handles an opaque thread_ref.

Path selection is operator state, never automatic failover. An adapter whose
path is down raises ChannelUnavailable; the runner stages the batch.
"""
from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from mahdawi.messaging.models import Capabilities, InboundItem


class ChannelUnavailable(RuntimeError):
    """The selected path cannot serve this run. Never a signal to try another."""


@runtime_checkable
class Channel(Protocol):
    def capabilities(self) -> Capabilities:
        """Post: the same values for the whole run."""

    def fetch_inbound(self) -> List[InboundItem]:
        """
        Post: every item carries a tz-aware created_at and a channel name equal
              to capabilities().name.
        Raises: ChannelUnavailable when the path is down.
        """

    def send(self, thread_ref: str, text: str) -> str:
        """
        Pre : the caller is messaging.dispatch. No other module may call this.
        Post: returns a provider message id.
        Raises: ChannelUnavailable when the path is down.
        """
