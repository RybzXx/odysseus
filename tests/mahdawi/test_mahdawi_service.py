"""
tests/mahdawi/test_mahdawi_service.py

The Platforms module lifecycle on the host DB: stage -> approve -> package ->
posted, dedupe, and the no-price flag. No network, no Playwright, no Supabase.
Uses the vendored AFOZC fixture (a real Fedshi product capture).
"""
import json
import os

import pytest

import core.database as db
from mahdawi.fedshi.models import ProductRecord
from mahdawi.fedshi.parse import build_record
from services import mahdawi as svc

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                       "mahdawi", "fedshi", "_fixtures", "AFOZC.json")


@pytest.fixture()
def session(tmp_path, monkeypatch):
    # Media/packages land under a temp dir, not the repo.
    monkeypatch.setenv("ODYSSEUS_DATA_DIR", str(tmp_path))
    db.init_db()                       # ensure mahdawi_posts exists on the test engine
    s = db.SessionLocal()
    # clean any prior rows so the test is deterministic on a shared in-memory DB
    s.query(db.MahdawiPost).delete()
    s.commit()
    yield s
    s.close()


def _record():
    return build_record(json.load(open(FIXTURE, encoding="utf-8")), "AFOZC")


def _fake_media(tmp_path):
    mdir = os.path.join(svc.media_root(), "AFOZC")
    os.makedirs(mdir, exist_ok=True)
    paths = []
    for n in ("1736150.mp4", "1736123.png"):
        p = os.path.join(mdir, n)
        open(p, "wb").write(b"bytes")
        paths.append(p)
    return {"AFOZC": paths}


def test_full_lifecycle(session, tmp_path):
    rec = _record()
    media = _fake_media(tmp_path)

    rep = svc.stage_records(session, [rec], media, owner="u1")
    assert rep["staged"] == 1 and rep["skipped_duplicate"] == 0

    # catalog fields: variants carry the colours read off the page
    staged = svc.list_products(session, owner="u1")[0]
    assert staged["variants"] == ["Black"]
    assert staged["posted_at"] is None and staged["post_urls"] == {}

    # dedupe: a second stage of the same sku is a no-op
    rep2 = svc.stage_records(session, [rec], media, owner="u1")
    assert rep2["staged"] == 0 and rep2["skipped_duplicate"] == 1

    # packaging before approval is refused
    with pytest.raises(svc.BadState):
        svc.build_package(session, "AFOZC", owner="u1")

    svc.approve(session, "AFOZC", owner="u1")
    pkg = svc.build_package(session, "AFOZC", owner="u1")
    files = set(os.listdir(pkg))
    assert {"caption.txt", "meta.json", "1736150.mp4", "1736123.png"} <= files

    caption = open(os.path.join(pkg, "caption.txt"), encoding="utf-8").read()
    # Short style (spec 2): the CTA and the trust line carry the caption, and the
    # price is absent because the media renders it instead (spec 2.3).
    assert "عالخاص" in caption
    assert "الدفع عند الاستلام" in caption
    assert "السعر" not in caption

    meta = json.load(open(os.path.join(pkg, "meta.json"), encoding="utf-8"))
    assert meta["sku"] == "AFOZC" and meta["price"] and meta["price"] > 0

    posted = svc.mark_posted(session, "AFOZC", owner="u1",
                             post_urls={"instagram": "https://instagram.com/p/xyz"})
    assert svc.platform_status(session, "u1")["counts"]["posted"] == 1
    assert posted["posted_at"] is not None
    assert posted["post_urls"]["instagram"] == "https://instagram.com/p/xyz"


def test_no_price_flagged(session):
    rec = ProductRecord(sku="NOPRICE", title="بلا سعر", wholesale_price=None,
                        profit_hint=None, reselling_price_min=None)
    rep = svc.stage_records(session, [rec], {}, owner="u1")
    assert "NOPRICE" in rep["flagged"]


def test_rejected_product_carries_tier_and_cannot_be_approved(session):
    # A 1,000 IQD profit hint is Fedshi's floor filler, so the rubric rejects it.
    rec = ProductRecord(sku="TRAP", title="سلعة", wholesale_price=15300,
                        profit_hint=1000, stock_band="50-75",
                        image_urls=["a.jpg", "b.jpg", "c.jpg"])
    svc.stage_records(session, [rec], {}, owner="u1")
    row = [p for p in svc.list_products(session, owner="u1") if p["sku"] == "TRAP"][0]
    assert row["tier"] == "REJECTED"
    assert row["gate_reasons"], "a rejection must say why"

    with pytest.raises(svc.BadState):
        svc.approve(session, "TRAP", owner="u1")


def test_good_product_is_tiered_and_approves(session):
    rec = ProductRecord(sku="GOOD", title="ستائر", category="المنزل والتنظيم",
                        wholesale_price=3900, profit_hint=8000, stock_band="100-200",
                        image_urls=["a.jpg", "b.jpg", "c.jpg"])
    svc.stage_records(session, [rec], {}, owner="u1")
    row = [p for p in svc.list_products(session, owner="u1") if p["sku"] == "GOOD"][0]
    assert row["tier"] == "A"
    assert row["gate_reasons"] == []
    assert row["content_type"] == "product"
    assert svc.approve(session, "GOOD", owner="u1")["status"] == "approved"


def test_owner_isolation(session):
    rec = _record()
    svc.stage_records(session, [rec], {}, owner="u1")
    # a different owner sees nothing and can re-stage the same sku is blocked by
    # the unique sku constraint, so cross-owner staging of the same sku raises;
    # here we only assert visibility isolation.
    assert svc.list_products(session, owner="u2") == []
    assert len(svc.list_products(session, owner="u1")) == 1
