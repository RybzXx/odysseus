"""
messaging.runner — one pass over one channel, and the report it produces.

    ingest -> gate -> classify (L2) -> tier -> write (L2) -> dispatch -> audit

For every item, whatever fails:
  * exactly one terminal state is written, and
  * a failure at any layer produces a staged or flagged row, never a send.

A gate-blocked item never reaches Gemini: an expired window or a reached cap
is settled by code.
"""
from __future__ import annotations

from mahdawi.messaging import dispatch as dispatch_mod
from mahdawi.messaging import gate, ingest as ingest_mod, store, tiers
from mahdawi.messaging.agents import Classifier, ReplyWriter
from mahdawi.messaging.channels import ChannelUnavailable
from mahdawi.messaging.models import (
    BLOCK_AGENT_UNAVAILABLE, BLOCK_PATH_UNAVAILABLE, Draft, InboundItem, RunReport,
    STATE_AUTO_REPLIED, STATE_FLAGGED, STATE_STAGED, ShopFacts,
)
from mahdawi.messaging.staging import stage_change


def _agent_failed(conn, item, facts, exc, *, tier=None, verdict=None) -> tuple:
    reason = "%s: %s" % (BLOCK_AGENT_UNAVAILABLE, exc.__class__.__name__)
    state = stage_change(conn, item, reason, tier=tier, verdict=verdict, facts=facts)
    store.write_classification(conn, channel=item.channel, external_id=item.external_id,
                               tier=tier, verdict=verdict, gate_facts=facts,
                               outcome=state, reason=reason)
    return state, reason, tier


def process(conn, channel, item: InboundItem, classifier: Classifier,
            writer: ReplyWriter, shop: ShopFacts) -> tuple:
    """
    One item, start to terminal state. Returns (state, reason, tier).

    Pre : item is claimed and unresolved.
    Post: the messages row holds a terminal state and exactly one
          classifications row exists for this item.
    """
    caps = channel.capabilities()
    result = gate.evaluate(conn, item, caps)

    if not result.passed:
        state = stage_change(conn, item, result.blocked_reason, facts=result.facts)
        store.write_classification(conn, channel=item.channel, external_id=item.external_id,
                                   tier=None, verdict=None, gate_facts=result.facts,
                                   outcome=state, reason=result.blocked_reason)
        return state, result.blocked_reason, None

    try:
        verdict = classifier.classify(gate.agent_payload(item, result.facts))
    except Exception as exc:
        return _agent_failed(conn, item, result.facts, exc)

    tier = tiers.assign(verdict, result.facts)
    try:
        draft = Draft(text=writer.write(item, verdict, shop))
    except Exception as exc:
        return _agent_failed(conn, item, result.facts, exc, tier=tier, verdict=verdict)

    state, reason = dispatch_mod.dispatch(conn, channel, item, tier, draft,
                                          verdict, result.facts, shop)
    store.write_classification(conn, channel=item.channel, external_id=item.external_id,
                               tier=tier, verdict=verdict, gate_facts=result.facts,
                               outcome=state,
                               reason=reason or tiers.reason_for(tier, verdict, result.facts))
    return state, reason, tier


def run(conn, channel, classifier: Classifier, writer: ReplyWriter,
        shop: ShopFacts) -> RunReport:
    """
    One pass: resume what an earlier run left, then take what is new.

    Post: report.balanced() is True.
    """
    report = RunReport()
    name = channel.capabilities().name
    pending = ingest_mod.resume(conn, name)

    try:
        fresh, duplicates = ingest_mod.ingest(conn, channel)
    except ChannelUnavailable:
        for item in pending:
            stage_change(conn, item, BLOCK_PATH_UNAVAILABLE)
            report.flagged += 1
            report.ingested += 1
            report.flags.append((item.external_id, BLOCK_PATH_UNAVAILABLE))
        store.write_run(conn, report.to_dict())
        return report

    report.skipped_duplicate = duplicates
    report.ingested = len(pending) + len(fresh) + duplicates

    for item in pending + fresh:
        state, reason, tier = process(conn, channel, item, classifier, writer, shop)
        if tier:
            report.classified += 1
            report.per_tier[tier] = report.per_tier.get(tier, 0) + 1
        if state == STATE_AUTO_REPLIED:
            report.auto_replied += 1
        elif state == STATE_STAGED:
            report.staged += 1
        elif state == STATE_FLAGGED:
            report.flagged += 1
        if reason:
            report.flags.append((item.external_id, reason))

    store.write_run(conn, report.to_dict())
    return report
