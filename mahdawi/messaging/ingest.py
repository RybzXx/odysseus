"""
messaging.ingest — normalize, then record, before any thinking happens.

The ledger write comes first. A crash between ingest and classification leaves
the item recorded with terminal_state NULL, and the next run resumes it.
Duplicate suppression is the atomic INSERT in store.claim.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple

from mahdawi.messaging import store
from mahdawi.messaging.models import InboundItem, KIND_COMMENT, KIND_DM


class MalformedItem(ValueError):
    """An adapter emitted an item core cannot process. An adapter bug."""


def validate(item: InboundItem, channel_name: str) -> None:
    """
    Pre : item came from the adapter named channel_name.
    Raises MalformedItem — blame sits with the adapter.
    """
    if item.channel != channel_name:
        raise MalformedItem("channel mismatch: %r from adapter %r" % (item.channel, channel_name))
    if not item.external_id or not item.thread_ref:
        raise MalformedItem("external_id and thread_ref are both required")
    if item.kind not in (KIND_DM, KIND_COMMENT):
        raise MalformedItem("unknown kind %r" % item.kind)
    if item.created_at.tzinfo is None:
        raise MalformedItem("created_at must be tz-aware; the window clock reads it")
    item.created_at = item.created_at.astimezone(timezone.utc)


def ingest(conn, channel) -> Tuple[List[InboundItem], int]:
    """
    Post: (new_items, duplicate_count). Every returned item holds a ledger row
          with no terminal state yet.
    Raises ChannelUnavailable — the runner stages the batch.
    """
    name = channel.capabilities().name
    fetched = channel.fetch_inbound()
    new_items, duplicates = [], 0
    for item in fetched:
        validate(item, name)
        if store.claim(conn, item):
            new_items.append(item)
        else:
            duplicates += 1
    return new_items, duplicates


def resume(conn, channel_name: str) -> List[InboundItem]:
    """Post: items an earlier run claimed and never resolved, rebuilt from the ledger."""
    return [InboundItem(channel=r["channel"], external_id=r["external_id"],
                        thread_ref=r["thread_ref"], kind=r["kind"], text=r["text"],
                        author_ref=r["author_ref"],
                        created_at=datetime.fromisoformat(r["created_at"]))
            for r in store.unresolved(conn, channel_name)]
