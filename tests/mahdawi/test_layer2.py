"""
tests/mahdawi/test_layer2.py

Layer Two (Gemini via 9router) and the Layer One checks around it: the gateway
fails in one shape, every output passes a code check or is refused, and the
pipeline stages a product only with checked Layer Two output. No network.
"""
import json
import os
import struct

import httpx
import pytest

import core.database as db
from mahdawi.content import media_check, text_check
from mahdawi.fedshi.models import ProductRecord
from mahdawi.layer2 import caption_line, image_judge, market_note, ranking
from mahdawi.layer2.gateway import Gateway, GatewayUnavailable, Layer2Failure, OutputRejected
from services import mahdawi as svc

from tests.mahdawi.fake_layer2 import FakeGateway, http_post


# -- gateway -------------------------------------------------------------------
def test_gateway_returns_the_answer_text():
    gw = Gateway("http://localhost:20128/v1", post=http_post(content=" هلا "))
    assert gw.url == "http://localhost:20128/v1/chat/completions"
    assert gw.complete("m", []) == "هلا"


@pytest.mark.parametrize("gw", [
    Gateway("http://x/v1", post=http_post(exc=httpx.ConnectError("refused"))),
    Gateway("http://x/v1", post=http_post(status=500)),
    Gateway("http://x/v1", post=http_post(content="  ")),
    Gateway(None),
])
def test_every_gateway_failure_is_gateway_unavailable(gw):
    with pytest.raises(GatewayUnavailable):
        gw.complete("m", [])


def test_non_json_answer_is_rejected_and_fenced_json_parses():
    with pytest.raises(OutputRejected):
        Gateway("http://x", post=http_post(content="sure!")).complete_json("m", [], lambda d: None)
    fenced = '```json\n{"ok": true}\n```'
    assert Gateway("http://x", post=http_post(content=fenced)).complete_json(
        "m", [], lambda d: None) == {"ok": True}


# -- Layer One text check --------------------------------------------------------
def test_numbers_are_read_in_every_digit_script():
    assert text_check.numbers_in("السعر ١٥٬٠٠٠ دينار و 3 قطع") == [15000, 3]


def test_a_number_code_did_not_supply_is_refused():
    found = text_check.problems("السعر ١٥٬٠٠٠ دينار", max_chars=200, min_arabic_share=0.7,
                                allowed_numbers={25000})
    assert any("numbers" in p for p in found)
    assert text_check.problems("السعر ٢٥٬٠٠٠ دينار", max_chars=200, min_arabic_share=0.7,
                               allowed_numbers={25000}) == []


def test_promise_terms_only_block_when_asked():
    text = "عدنا خصم خاص الك"
    assert text_check.problems(text, max_chars=200, min_arabic_share=0.7) == []
    assert text_check.problems(text, max_chars=200, min_arabic_share=0.7, forbid_promises=True)


@pytest.mark.parametrize("line", [
    "بس بـ 15000 دينار",                  # a price Gemini invented
    "يساعد على حرق الدهون بسرعة",           # a banned claim
    "best product ever, buy now",           # not Arabic
    "خوش منتج 😍",                          # emoji
    "خوش " * 60,                            # too long
])
def test_caption_line_check_refuses_unsafe_lines(line):
    assert caption_line.check_line(line) is not None


def test_caption_line_check_accepts_a_clean_line():
    assert caption_line.check_line("خوش اختيار للبيت، عملي وسهل الاستعمال.") is None


# -- ranking check ----------------------------------------------------------------
def _entry(sku, rank):
    return {"sku": sku, "rank": rank, "reason": "سبب"}


@pytest.mark.parametrize("data", [
    [_entry("A", 1)],                                    # a candidate is missing
    [_entry("A", 1), _entry("B", 2), _entry("C", 3)],    # an sku that was not sent
    [_entry("A", 1), _entry("B", 1)],                    # a repeated rank
    [_entry("A", 1), _entry("A", 2)],                    # a repeated sku
    [_entry("A", True), _entry("B", 2)],                 # a bool rank
    {"A": 1},                                            # not a list
])
def test_ranking_check_refuses_anything_but_the_candidates_ranked_once(data):
    assert ranking.check_ranking(data, ["A", "B"]) is not None


def test_ranking_check_accepts_a_permutation():
    assert ranking.check_ranking([_entry("B", 1), _entry("A", 2)], ["A", "B"]) is None


def test_note_and_image_verdict_checks():
    assert market_note.check_note({"buyer": "x", "season": "", "angle": "y"})
    assert market_note.check_note({"buyer": "x", "season": "s", "angle": "y"}) is None
    assert image_judge.check_verdict({"ok": False, "reasons": []})
    assert image_judge.check_verdict({"ok": "yes"})
    assert image_judge.check_verdict({"ok": False, "reasons": ["watermark"]}) is None


# -- Layer One media check ----------------------------------------------------------
def _png(path, w, h, salt=b""):
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", w, h)
                + b"\x08\x02\x00\x00\x00" + salt)
    return str(path)


def _jpeg(path, w, h):
    sof = b"\xff\xc0" + struct.pack(">HBHH", 11, 8, h, w) + b"\x03\x01\x11\x00"
    with open(path, "wb") as f:
        f.write(b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 4) + b"JF" + sof + b"\xff\xd9")
    return str(path)


def test_media_check_sizes_png_and_jpeg(tmp_path):
    assert media_check.image_size(_png(tmp_path / "a.png", 800, 600)) == (800, 600)
    assert media_check.image_size(_jpeg(tmp_path / "b.jpg", 1080, 1350)) == (1080, 1350)


def test_media_check_drops_small_duplicate_unreadable_and_missing(tmp_path):
    good = _png(tmp_path / "good.png", 800, 800, b"1")
    copy = _png(tmp_path / "copy.png", 800, 800, b"1")
    small = _png(tmp_path / "small.png", 100, 100, b"2")
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not an image")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    kept, dropped = media_check.check_media(
        [str(video), good, copy, small, str(junk), str(tmp_path / "gone.png")])
    assert kept == [str(video), good]
    assert [n for n, _ in dropped] == ["copy.png", "small.png", "junk.png", "gone.png"]


# -- the pipeline --------------------------------------------------------------------
@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("ODYSSEUS_DATA_DIR", str(tmp_path))
    db.init_db()
    s = db.SessionLocal()
    s.query(db.MahdawiPost).delete()
    s.commit()
    yield s
    s.close()


def _good(sku="GOOD"):
    return ProductRecord(sku=sku, title="ستائر", category="المنزل والتنظيم",
                         description="ستائر عملية", wholesale_price=3900, profit_hint=8000,
                         stock_band="100-200", image_urls=["a.jpg", "b.jpg", "c.jpg"])


def _media(sku, n=2):
    mdir = os.path.join(svc.media_root(), sku)
    os.makedirs(mdir, exist_ok=True)
    return {sku: [_png(os.path.join(mdir, "%d.png" % i), 800, 800, bytes([i]))
                  for i in range(n)]}


def _row(session, sku):
    session.expire_all()
    return svc.get_post(session, sku, "u1")


def test_layer2_writes_the_caption_line_note_and_rank(session):
    gw = FakeGateway()
    rep = svc.stage_records(session, [_good()], _media("GOOD"), "u1", gw)
    row = _row(session, "GOOD")
    assert rep["staged"] == 1 and rep["rank_error"] is None
    assert row.status == svc.STATUS_STAGED
    assert "خوش اختيار للبيت" in row.caption          # Gemini's line
    assert "عالخاص" in row.caption                      # code's CTA survives
    assert row.market_note.startswith("المشتري:")
    assert row.rank == 1 and row.rank_reason
    assert gw.calls.count("image") == 2


def test_9router_down_leaves_the_product_waiting_not_code_written(session):
    gw = FakeGateway()
    gw.down = True
    rep = svc.stage_records(session, [_good()], _media("GOOD"), "u1", gw)
    row = _row(session, "GOOD")
    assert rep["waiting_layer2"] == 1 and rep["staged"] == 0
    assert row.status == svc.STATUS_WAITING_LAYER2
    assert row.caption is None and "9router is down" in row.layer2_error
    with pytest.raises(svc.BadState):
        svc.approve(session, "GOOD", "u1")

    gw.down = False                                   # 9router is back
    out = svc.retry_waiting(session, gw, "u1")
    row = _row(session, "GOOD")
    assert out == {"staged": 1, "still_waiting": 0, "rank_error": None}
    assert row.status == svc.STATUS_STAGED and "خوش اختيار" in row.caption
    assert svc.approve(session, "GOOD", "u1")["status"] == "approved"


def test_a_rejected_caption_line_leaves_the_product_waiting(session):
    gw = FakeGateway(line="بس بـ 15000 دينار")
    svc.stage_records(session, [_good()], _media("GOOD"), "u1", gw)
    row = _row(session, "GOOD")
    assert row.status == svc.STATUS_WAITING_LAYER2
    assert "numbers" in row.layer2_error


def test_rubric_rejects_before_any_layer2_call(session):
    trap = ProductRecord(sku="TRAP", title="سلعة", wholesale_price=15300, profit_hint=1000,
                         stock_band="50-75", image_urls=["a", "b", "c"])
    gw = FakeGateway()
    svc.stage_records(session, [trap], _media("TRAP"), "u1", gw)
    assert _row(session, "TRAP").tier == "REJECTED"
    assert [c for c in gw.calls if c != "rank"] == []


def test_every_image_refused_rejects_the_product(session):
    gw = FakeGateway(image=json.dumps({"ok": False, "reasons": ["another shop's logo"]}))
    svc.stage_records(session, [_good()], _media("GOOD"), "u1", gw)
    row = _row(session, "GOOD")
    assert row.tier == "REJECTED" and row.media_files == []
    assert any("another shop's logo" in f for f in row.flags)
    assert "note" not in gw.calls                     # no text written for it


def test_a_failed_ranking_keeps_the_drafts(session):
    gw = FakeGateway(rank=json.dumps([{"sku": "OTHER", "rank": 1, "reason": "x"}]))
    rep = svc.stage_records(session, [_good()], _media("GOOD"), "u1", gw)
    assert rep["staged"] == 1 and "skus differ" in rep["rank_error"]
    assert _row(session, "GOOD").rank is None


def test_layer2_off_stages_code_only_drafts(session):
    rep = svc.stage_records(session, [_good()], _media("GOOD"), "u1", None)
    row = _row(session, "GOOD")
    assert rep["staged"] == 1 and row.market_note is None and row.rank is None


def test_gateway_for_a_missing_9router_row_fails_every_call(session, monkeypatch):
    session.query(db.ModelEndpoint).filter(
        db.ModelEndpoint.id == db._ENDPOINT_9ROUTER_ID).delete()
    session.commit()
    gw = svc.layer2_gateway(session)
    with pytest.raises(Layer2Failure):
        gw.complete("m", [])
