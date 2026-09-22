"""
tests/mahdawi/test_messaging.py

Customer replies: Gemini reads and writes, code decides. A reply auto-sends only
when code tiered it FAQ, the owner turned auto-send on, and the reply passes the
code check. Every other path stages or flags, and a failure never sends.
"""
import json
from datetime import timedelta
from typing import List

import pytest

from mahdawi.layer2.gateway import OutputRejected
from mahdawi.layer2.replies import GeminiClassifier, GeminiReplyWriter
from mahdawi.messaging import runner, settings, store
from mahdawi.messaging.channels import ChannelUnavailable
from mahdawi.messaging.models import (
    AgentVerdict, Capabilities, InboundItem, KIND_DM, STAGE_AUTOSEND_OFF,
    STAGE_REPLY_CHECK_FAILED, STAGE_TIER_REQUIRES_APPROVAL, STATE_AUTO_REPLIED,
    ShopFacts, TIER_FAQ, TIER_TRANSACTION, utcnow,
)

from tests.mahdawi.fake_layer2 import FakeGateway

SHOP = ShopFacts(lines=(("delivery_and_payment", "توصيل لجميع المحافظات - الدفع عند الاستلام"),),
                 products=(("ستائر", 11900),))


class MockChannel:
    def __init__(self, items: List[InboundItem], available=True, can_send=True):
        self.items, self.available, self.sent = list(items), available, []
        self._caps = Capabilities(name="instagram", can_send=can_send,
                                  reply_window_seconds=24 * 3600,
                                  supports_comment_reply=True, text_byte_limit=1000)

    def capabilities(self):
        return self._caps

    def fetch_inbound(self):
        if not self.available:
            raise ChannelUnavailable("instagram")
        return list(self.items)

    def send(self, thread_ref, text):
        self.sent.append((thread_ref, text))
        return "mock-%d" % len(self.sent)


def _item(eid="m1", text="بشكد الستائر؟", age_hours=0.0, thread="t1"):
    return InboundItem(channel="instagram", external_id=eid, thread_ref=thread, kind=KIND_DM,
                       text=text, author_ref="u", created_at=utcnow() - timedelta(hours=age_hours))


class FixedClassifier:
    def __init__(self, tier=TIER_FAQ, confidence=0.95, tone="neutral", fail=False):
        self.v = AgentVerdict("price", tier, tone, confidence, "fixed")
        self.fail, self.calls = fail, 0

    def classify(self, payload):
        self.calls += 1
        if self.fail:
            raise OutputRejected("bad verdict")
        return self.v


class FixedWriter:
    def __init__(self, text="هلا بيك، سعر الستائر ١١٬٩٠٠ دينار.", fail=False):
        self.text, self.fail = text, fail

    def write(self, item, verdict, facts):
        if self.fail:
            raise OutputRejected("bad reply")
        return self.text


@pytest.fixture()
def conn():
    c = store.connect(":memory:")
    yield c
    c.close()


@pytest.fixture()
def autosend(monkeypatch):
    monkeypatch.setattr(settings, "AUTOSEND", True)


def _run(conn, channel, classifier=None, writer=None):
    rep = runner.run(conn, channel, classifier or FixedClassifier(), writer or FixedWriter(), SHOP)
    assert rep.balanced()
    return rep


def test_routine_reply_with_a_real_price_auto_sends(conn, autosend):
    ch = MockChannel([_item()])
    rep = _run(conn, ch)
    assert rep.auto_replied == 1 and len(ch.sent) == 1
    assert store.audit_count(conn, STATE_AUTO_REPLIED) == 1


def test_autosend_off_stages_even_a_clean_faq_reply(conn):
    ch = MockChannel([_item()])
    rep = _run(conn, ch)
    assert rep.staged == 1 and ch.sent == []
    assert store.staged_rows(conn)[0]["reason"] == STAGE_AUTOSEND_OFF


@pytest.mark.parametrize("text", [
    "هلا بيك، سعر الستائر ٩٬٠٠٠ دينار.",       # a price code never set
    "هلا بيك، عدنا خصم على الستائر.",           # a promise only the owner makes
])
def test_a_reply_failing_the_code_check_stages(conn, autosend, text):
    ch = MockChannel([_item()])
    rep = _run(conn, ch, writer=FixedWriter(text))
    row = store.staged_rows(conn)[0]
    assert rep.staged == 1 and ch.sent == []
    assert row["reason"] == STAGE_REPLY_CHECK_FAILED and row["payload"]["check_problems"]


def test_transaction_and_low_confidence_stage(conn, autosend):
    ch = MockChannel([_item("a", thread="t1"), _item("b", thread="t2")])
    rep = _run(conn, ch, classifier=FixedClassifier(tier=TIER_TRANSACTION))
    assert rep.staged == 2 and ch.sent == []
    assert {r["reason"] for r in store.staged_rows(conn)} == {STAGE_TIER_REQUIRES_APPROVAL}

    ch2 = MockChannel([_item("c", thread="t3")])
    _run(conn, ch2, classifier=FixedClassifier(confidence=0.4))
    assert ch2.sent == []


def test_agent_failures_flag_and_never_send(conn, autosend):
    ch = MockChannel([_item("a", thread="t1"), _item("b", thread="t2")])
    rep = _run(conn, ch, classifier=FixedClassifier(fail=True))
    assert rep.flagged == 2 and ch.sent == []

    ch2 = MockChannel([_item("c", thread="t3")])
    rep2 = _run(conn, ch2, writer=FixedWriter(fail=True))
    assert rep2.flagged == 1 and ch2.sent == []


def test_expired_window_never_reaches_gemini(conn, autosend):
    clf = FixedClassifier()
    ch = MockChannel([_item(age_hours=30)])
    rep = _run(conn, ch, classifier=clf)
    assert rep.flagged == 1 and clf.calls == 0 and ch.sent == []


def test_duplicate_is_processed_once(conn, autosend):
    ch = MockChannel([_item()])
    _run(conn, ch)
    rep = _run(conn, ch)
    assert rep.skipped_duplicate == 1 and len(ch.sent) == 1


def test_channel_down_sends_nothing(conn, autosend):
    rep = _run(conn, MockChannel([_item()], available=False))
    assert rep.ingested == 0 and rep.auto_replied == 0


def test_shop_facts_allow_only_supplied_numbers():
    assert 11900 in SHOP.allowed_numbers() and 9000 not in SHOP.allowed_numbers()


# -- the Gemini agents, over the fake gateway ------------------------------------------
def test_gemini_classifier_reads_a_checked_verdict():
    v = GeminiClassifier(FakeGateway()).classify({"text": "بشكد؟", "kind": "dm", "facts": {}})
    assert v.tier_signal == TIER_FAQ and v.confidence == 0.95


def test_gemini_classifier_refuses_an_out_of_range_verdict():
    bad = json.dumps({"intent": "price", "tier_signal": "AUTO_SEND", "tone": "neutral",
                      "confidence": 0.9, "reasoning": "x"})
    with pytest.raises(OutputRejected):
        GeminiClassifier(FakeGateway(classify=bad)).classify({"text": "x"})


def test_gemini_writer_refuses_an_invented_price():
    verdict = AgentVerdict("price", TIER_FAQ, "neutral", 0.9, "x")
    with pytest.raises(OutputRejected):
        GeminiReplyWriter(FakeGateway(reply="السعر ٥٠٠٠ دينار")).write(_item(), verdict, SHOP)
    ok = GeminiReplyWriter(FakeGateway(reply="السعر ١١٬٩٠٠ دينار")).write(_item(), verdict, SHOP)
    assert "١١٬٩٠٠" in ok
