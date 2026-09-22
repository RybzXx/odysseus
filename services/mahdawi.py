"""
services/mahdawi.py — the Platforms module logic, over the host DB.

Reuses the vendored stateless engines (mahdawi.content for price+caption,
mahdawi.fedshi for extraction+media) and keeps all state in one SQLAlchemy
model, MahdawiPost. Nothing here posts to a platform: a human approves, then
packaging builds a folder to post by hand.

Two layers compose a product. Layer One (code) prices it, gates it, and checks
its files. Layer Two (Gemini via 9router, mahdawi.layer2) judges its images,
writes its market note and caption line, and ranks the open products. When
Layer Two fails, the product waits (STATUS_WAITING_LAYER2) rather than falling
back to code-written text.

The fetch run (run_fetch) drives Playwright, which is a blocking sync API, so a
route calls it through asyncio.to_thread. Playwright is imported lazily inside
run_fetch, so the module — and the dashboard — load even where Playwright is
not installed; only a fetch needs it.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from core.database import (
    MahdawiPost, ModelEndpoint, SessionLocal, _ENDPOINT_9ROUTER_ID, utcnow_naive,
)
from mahdawi.content import caption as caption_mod
from mahdawi.content import compose, media_check, media_select, pricing, scoring
from mahdawi.content import settings as content_settings
from mahdawi.content.models import FLAG_NO_MEDIA, FLAG_NO_PRICE
from mahdawi.fedshi.models import ProductRecord
from mahdawi.layer2 import caption_line, image_judge, market_note, ranking
from mahdawi.layer2 import settings as layer2_settings
from mahdawi.layer2.gateway import Gateway, Layer2Failure

STATUS_STAGED = "staged"
STATUS_APPROVED = "approved"
STATUS_PACKAGED = "packaged"
STATUS_POSTED = "posted"
# Passed the Layer One gates, but a Layer Two step (Gemini via 9router) failed.
# The row holds its Fedshi facts and waits for retry_waiting(); it cannot be
# approved, because it has no checked caption yet.
STATUS_WAITING_LAYER2 = "waiting_layer2"

FLAG_MEDIA_DROPPED = "MEDIA_DROPPED"

_FEDSHI_PRODUCT_URL = "https://web.fedshi.com/products/%s"


def _data_dir() -> str:
    root = os.environ.get(
        "ODYSSEUS_DATA_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
    return os.path.join(root, "mahdawi")


def media_root() -> str:
    return os.path.join(_data_dir(), "media")


def package_root() -> str:
    return os.path.join(_data_dir(), "packages")


# -- serialization -----------------------------------------------------------
def post_to_dict(row: MahdawiPost) -> dict:
    """Post: a JSON-safe view of a MahdawiPost for the dashboard."""
    return {
        "id": row.id, "sku": row.sku, "title": row.title, "caption": row.caption,
        "price": row.price, "profit": row.profit, "status": row.status,
        "media_files": row.media_files or [], "channels": row.channels or [],
        "flags": row.flags or [], "package_dir": row.package_dir,
        "fedshi_url": row.fedshi_url or (_FEDSHI_PRODUCT_URL % row.sku),
        "thumb_url": row.thumb_url,
        "tier": row.tier, "gate_reasons": row.gate_reasons or [],
        "content_type": row.content_type, "transform_state": row.transform_state,
        "overlay_price_rendered": bool(row.overlay_price_rendered),
        "category": row.category, "original_price": row.original_price,
        "discount_pct": row.discount_pct, "variants": row.variants or [],
        "curation_score": row.curation_score,
        "market_note": row.market_note, "rank": row.rank, "rank_reason": row.rank_reason,
        "layer2_error": row.layer2_error,
        "views": row.views, "orders": row.orders, "post_urls": row.post_urls or {},
        "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
        "posted_at": row.posted_at.isoformat() if row.posted_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# -- read --------------------------------------------------------------------
def get_post(db: Session, sku: str, owner: Optional[str] = None) -> Optional[MahdawiPost]:
    q = db.query(MahdawiPost).filter(MahdawiPost.sku == sku)
    if owner is not None:
        q = q.filter(MahdawiPost.owner == owner)
    return q.first()


def list_products(db: Session, status: Optional[str] = None,
                  owner: Optional[str] = None) -> List[dict]:
    q = db.query(MahdawiPost)
    if owner is not None:
        q = q.filter(MahdawiPost.owner == owner)
    if status:
        q = q.filter(MahdawiPost.status == status)
    return [post_to_dict(r) for r in q.order_by(MahdawiPost.updated_at.desc()).all()]


def platform_status(db: Session, owner: Optional[str] = None) -> dict:
    """Per-status counts plus the gathered total, for the platform cards."""
    q = db.query(MahdawiPost)
    if owner is not None:
        q = q.filter(MahdawiPost.owner == owner)
    rows = q.all()
    counts = {STATUS_STAGED: 0, STATUS_APPROVED: 0, STATUS_PACKAGED: 0, STATUS_POSTED: 0,
              STATUS_WAITING_LAYER2: 0}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    waiting = [r for r in rows if r.status == STATUS_WAITING_LAYER2]
    from mahdawi.fedshi import session as fedshi_session
    return {
        "gathered": len(rows),
        "counts": counts,
        "fedshi_session": fedshi_session.has_state(),
        "channels": ["instagram", "tiktok", "fedshi"],
        "layer2": {
            "enabled": layer2_settings.ENABLED,
            "writer_model": layer2_settings.MODEL_WRITER,
            "judge_model": layer2_settings.MODEL_JUDGE,
            "waiting": len(waiting),
            "last_error": waiting[0].layer2_error if waiting else None,
        },
    }


# -- Layer Two (Gemini via 9router) -------------------------------------------
def layer2_gateway(db: Session) -> Optional[Gateway]:
    """
    Post: None when Layer Two is switched off (operator state). Otherwise a
          Gateway for the seeded 9router endpoint; a missing or disabled row
          gives a Gateway whose every call fails, so products wait.
    """
    if not layer2_settings.ENABLED:
        return None
    row = db.get(ModelEndpoint, _ENDPOINT_9ROUTER_ID)
    if row is None or not row.is_enabled:
        return Gateway(None)
    headers = {"Authorization": "Bearer %s" % row.api_key} if row.api_key else {}
    return Gateway(row.base_url, headers)


def _layer2_content(gateway: Gateway, record: ProductRecord,
                    paths: List[str]) -> Tuple[List[str], List[Tuple[str, str]],
                                               Optional[str], Optional[str]]:
    """
    Layer One file checks, then every Layer Two step for one product that
    passed the rubric gates.

    Post: (kept_media, dropped_media, market_note, caption_line). When no media
          survives, note and line are None and no text call was made.
    Raises: Layer2Failure from any step; no partial result escapes.
    """
    kept, dropped = media_check.check_media(paths)
    # Post order first (videos, then images), so the carousel cap decides which
    # files Gemini judges and no call is spent on a file that cannot be posted.
    kept = media_select.order_media(kept, cap=len(kept))
    kept, judged_out = image_judge.filter_images(gateway, record, kept,
                                                 limit=content_settings.MEDIA_CAP)
    dropped += judged_out
    if not kept:
        return kept, dropped, None, None
    note = market_note.write_note(gateway, record)
    line = caption_line.write_line(gateway, record, note)
    return kept, dropped, note, line


def _apply_draft(row: MahdawiPost, draft) -> None:
    row.title = draft.title
    row.caption = draft.caption
    row.price = draft.price
    row.profit = draft.profit
    row.media_files = [os.path.basename(p) for p in draft.media_paths]
    row.channels = list(draft.target_channels)
    row.flags = list(draft.flags)


def _compose_row(row: MahdawiPost, record: ProductRecord, paths: List[str],
                 gateway: Optional[Gateway]) -> str:
    """
    Fill one row from its record. Returns the row's status.

    Pre : row.sku == record.sku; paths are the product's local media files.
    Post: STATUS_STAGED with a complete draft, or STATUS_WAITING_LAYER2 with
          layer2_error set and no caption.
    Invariant: a product the rubric rejects never costs a Layer Two call, and a
          product whose images Gemini all refuses is staged as REJECTED.
    """
    price, _profit, _flags = pricing.price(record)
    score = scoring.score_product(record, price=price)
    row.tier, row.gate_reasons = score.tier, list(score.reasons)

    if gateway is None or score.rejected:
        _apply_draft(row, compose.build_draft(record, media_paths=paths))
        row.status, row.layer2_error = STATUS_STAGED, None
        return row.status

    try:
        kept, dropped, note, line = _layer2_content(gateway, record, paths)
    except Layer2Failure as exc:
        row.media_files = [os.path.basename(p) for p in paths]
        row.caption, row.market_note = None, None
        row.status, row.layer2_error = STATUS_WAITING_LAYER2, str(exc)
        return row.status

    draft = compose.build_draft(record, media_paths=kept,
                                generator=(lambda _r: line) if line else None)
    _apply_draft(row, draft)
    if dropped:
        row.flags = row.flags + ["%s %s: %s" % (FLAG_MEDIA_DROPPED, n, why) for n, why in dropped]
    if not kept:
        row.tier = scoring.TIER_REJECTED
        row.gate_reasons = [scoring.GATE_MEDIA + ": no image passed the image check"]
    row.market_note = note
    row.status, row.layer2_error = STATUS_STAGED, None
    return row.status


def rank_open_products(db: Session, gateway: Gateway, owner: Optional[str] = None) -> int:
    """
    Gemini orders every product that passed the gates and is not yet posted.

    Post: each such row carries rank and rank_reason; returns how many.
    Raises: Layer2Failure — ranks keep their previous values.
    """
    q = db.query(MahdawiPost).filter(MahdawiPost.status.in_([STATUS_STAGED, STATUS_APPROVED]),
                                     MahdawiPost.tier.in_([scoring.TIER_A, scoring.TIER_B,
                                                           scoring.TIER_C]))
    if owner is not None:
        q = q.filter(MahdawiPost.owner == owner)
    rows = {r.sku: r for r in q.all()}
    candidates = [ranking.Candidate(
        sku=r.sku, title=r.title, category=r.category, tier=r.tier,
        margin_pct=(round(100.0 * r.profit / r.price, 1) if r.price and r.profit is not None
                    else None),
        price=r.price, market_note=r.market_note) for r in rows.values()]
    for ranked in ranking.rank(gateway, candidates):
        rows[ranked.sku].rank = ranked.rank
        rows[ranked.sku].rank_reason = ranked.reason
    db.commit()
    return len(candidates)


def _rank_after(db: Session, gateway: Optional[Gateway], owner: Optional[str]) -> Optional[str]:
    """Post: None when ranking ran or Layer Two is off; else the failure text."""
    if gateway is None:
        return None
    try:
        rank_open_products(db, gateway, owner)
        return None
    except Layer2Failure as exc:
        return str(exc)


# -- stage -------------------------------------------------------------------
def stage_records(db: Session, records: List[ProductRecord],
                  media_by_sku: Optional[Dict[str, List[str]]] = None,
                  owner: Optional[str] = None,
                  gateway: Optional[Gateway] = None) -> dict:
    """
    Compose each record and persist a MahdawiPost.

    Pre : records already fetched; media_by_sku maps sku -> local media paths.
          gateway None means Layer Two is off: no network, code-only drafts.
    Post: each new sku has a staged or waiting row; duplicates skip;
          no-price/no-media flag. With a gateway, open products are re-ranked.
    """
    media_by_sku = media_by_sku or {}
    staged, waiting, skipped, flagged = 0, 0, 0, []
    for record in records:
        if get_post(db, record.sku, owner):
            skipped += 1
            continue
        # A rejected product is still staged, so the dashboard can say why it
        # will not post, but approve() refuses to advance it.
        row = MahdawiPost(
            id=str(uuid.uuid4()), owner=owner, sku=record.sku, title=record.title,
            media_dir=os.path.join(media_root(), record.sku),
            fedshi_url=record.source_url or (_FEDSHI_PRODUCT_URL % record.sku),
            thumb_url=(record.image_urls[0] if record.image_urls else None),
            category=record.category,           # null until thread C confirms a source
            variants=list(record.colors or []),  # colours we already read off the page
            content_type="product", transform_state="pending",
            source_record=record.to_dict(),
        )
        status = _compose_row(row, record, media_by_sku.get(record.sku, []), gateway)
        db.add(row)
        if status == STATUS_WAITING_LAYER2:
            waiting += 1
        else:
            staged += 1
            if FLAG_NO_PRICE in row.flags or FLAG_NO_MEDIA in row.flags:
                flagged.append(record.sku)
    db.commit()
    return {"staged": staged, "waiting_layer2": waiting, "skipped_duplicate": skipped,
            "flagged": flagged, "rank_error": _rank_after(db, gateway, owner)}


def retry_waiting(db: Session, gateway: Gateway, owner: Optional[str] = None) -> dict:
    """
    Run Layer Two again for every product waiting on it.

    Pre : gateway is not None (Layer Two is on).
    Post: each waiting row is staged or still waiting with a fresh error; open
          products are re-ranked.
    """
    q = db.query(MahdawiPost).filter(MahdawiPost.status == STATUS_WAITING_LAYER2)
    if owner is not None:
        q = q.filter(MahdawiPost.owner == owner)
    done, still = 0, 0
    for row in q.all():
        record = ProductRecord.from_dict(row.source_record or {"sku": row.sku})
        paths = [os.path.join(row.media_dir or "", n) for n in (row.media_files or [])]
        if _compose_row(row, record, paths, gateway) == STATUS_WAITING_LAYER2:
            still += 1
        else:
            done += 1
    db.commit()
    return {"staged": done, "still_waiting": still,
            "rank_error": _rank_after(db, gateway, owner)}


# -- lifecycle ---------------------------------------------------------------
class NotFound(RuntimeError):
    pass


class BadState(RuntimeError):
    pass


def approve(db: Session, sku: str, owner: Optional[str] = None) -> dict:
    """
    Pre : status is staged and the product passed the rubric.
    Post: status approved.
    Invariant: a REJECTED product never advances, whatever a caller asks, so a
          gated product cannot reach packaging by way of the approve route.
    """
    row = get_post(db, sku, owner)
    if not row:
        raise NotFound(sku)
    if row.status != STATUS_STAGED:
        raise BadState("sku %s is %s, not staged" % (sku, row.status))
    if row.tier == scoring.TIER_REJECTED:
        raise BadState("sku %s failed the rubric: %s"
                       % (sku, "; ".join(row.gate_reasons or ["no reason recorded"])))
    row.status = STATUS_APPROVED
    db.commit()
    return post_to_dict(row)


def build_package(db: Session, sku: str, owner: Optional[str] = None) -> str:
    """
    Assemble an approved product into a folder to post by hand. No network.

    Pre : status is approved. Post: media + caption.txt + meta.json written,
          status packaged, package_dir recorded.
    """
    row = get_post(db, sku, owner)
    if not row:
        raise NotFound(sku)
    if row.status != STATUS_APPROVED:
        raise BadState("sku %s is %s, not approved" % (sku, row.status))

    pkg = os.path.join(package_root(), sku)
    os.makedirs(pkg, exist_ok=True)
    with open(os.path.join(pkg, "caption.txt"), "w", encoding="utf-8") as f:
        f.write(row.caption or "")
    # One caption per channel: the tag line is cut to each channel's cap.
    for channel in (row.channels or []):
        with open(os.path.join(pkg, "caption_%s.txt" % channel), "w", encoding="utf-8") as f:
            f.write(caption_mod.for_channel(row.caption or "", channel))
    copied = []
    for name in (row.media_files or []):
        src = os.path.join(row.media_dir or "", name)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(pkg, name))
            copied.append(name)
    meta = {"sku": sku, "title": row.title, "price": row.price, "profit": row.profit,
            "channels": row.channels or [], "flags": row.flags or [], "media": copied}
    with open(os.path.join(pkg, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    row.status = STATUS_PACKAGED
    row.package_dir = pkg
    db.commit()
    return pkg


def mark_posted(db: Session, sku: str, owner: Optional[str] = None,
                post_urls: Optional[Dict[str, str]] = None) -> dict:
    """
    Record that a post went live.

    Pre : the row exists. Post: status posted, posted_at stamped, and any
          per-channel URLs merged into post_urls (existing channels kept).
    """
    row = get_post(db, sku, owner)
    if not row:
        raise NotFound(sku)
    row.status = STATUS_POSTED
    row.posted_at = utcnow_naive()
    if post_urls:
        merged = dict(row.post_urls or {})
        merged.update(post_urls)
        row.post_urls = merged
    db.commit()
    return post_to_dict(row)


# -- drive a post onto a platform (blocking; call via asyncio.to_thread) ------
def _driver_for(channel: str):
    """Post: the driver class for the channel. Raises BadState for any other."""
    if channel == "instagram":
        from mahdawi.driver.instagram import InstagramDriver
        return InstagramDriver
    if channel == "tiktok":
        from mahdawi.driver.tiktok import TikTokDriver
        return TikTokDriver
    raise BadState("no driver for channel %r" % channel)


def drive_post(db: Session, sku: str, channel: str = "instagram",
               owner: Optional[str] = None, dry_run: bool = True) -> dict:
    """
    Drive an already-packaged product onto one platform through the phone.

    Pre : status is packaged and package_dir exists on disk.
    Post: dry_run -> a report, status unchanged, nothing posted. live -> the
          channel is recorded in post_urls and, once every target channel has
          posted, status posted and posted_at stamped.
    Invariant (fail closed, spec 0.3): a DriverError propagates and the row
          stays packaged, never a false "posted".
    """
    row = get_post(db, sku, owner)
    if not row:
        raise NotFound(sku)
    if row.status != STATUS_PACKAGED:
        raise BadState("sku %s is %s, not packaged" % (sku, row.status))
    if not row.package_dir or not os.path.isdir(row.package_dir):
        raise BadState("sku %s has no package on disk" % sku)

    result = _driver_for(channel)().post(row.package_dir, dry_run=dry_run)
    if not dry_run and result.get("status") == "posted":
        posted_channels = dict(row.post_urls or {})
        posted_channels[channel] = "posted by the driver"
        if all(c in posted_channels for c in (row.channels or [channel])):
            mark_posted(db, sku, owner, post_urls=posted_channels)
        else:
            row.post_urls = posted_channels
            db.commit()
    return result


# -- fetch run (Playwright, blocking; call via asyncio.to_thread) -------------
_RUNS: Dict[str, dict] = {}   # in-memory progress registry


def run_state(run_id: str) -> Optional[dict]:
    return _RUNS.get(run_id)


def run_fetch(run_id: str, skus: List[str], owner: Optional[str] = None,
              collection: Optional[str] = None) -> dict:
    """
    Fetch each SKU (or a collection's SKUs) with Playwright, download media,
    then stage. Blocking — a route runs this in a thread.

    Post: new products are staged with media on disk. A dead session ends the
          run with error SESSION_EXPIRED, not a crash.
    Invariant: dedupe precedes fetch, so a staged sku costs no browser call.
    """
    from mahdawi.fedshi import media as fedshi_media
    from mahdawi.fedshi.playwright_engine import PlaywrightFedshiSource
    from mahdawi.fedshi.source import SessionExpired

    run = _RUNS.setdefault(run_id, {"id": run_id, "state": "running", "done": 0,
                                    "total": 0, "staged": 0, "skipped": 0,
                                    "waiting_layer2": 0, "rank_error": None,
                                    "flagged": [], "error": None})
    db = SessionLocal()
    try:
        source = PlaywrightFedshiSource(headless=True)
        if collection:
            skus = [e.sku for e in source.fetch_listing(collection)]
        # dedupe before any fetch (review finding F9)
        skus = [s for s in skus if not get_post(db, s, owner)]
        run["total"] = len(skus)

        records, media_by_sku = [], {}
        for sku in skus:
            record = source.fetch(sku)
            paths = fedshi_media.download_all(
                record.image_urls + record.video_urls, os.path.join(media_root(), sku))
            records.append(record)
            media_by_sku[sku] = paths
            run["done"] += 1

        run["state"] = "writing"                 # Layer Two: Gemini via 9router
        report = stage_records(db, records, media_by_sku, owner, layer2_gateway(db))
        run.update(state="done", staged=report["staged"],
                   waiting_layer2=report["waiting_layer2"], rank_error=report["rank_error"],
                   skipped=report["skipped_duplicate"], flagged=report["flagged"])
    except SessionExpired:
        run.update(state="error", error="SESSION_EXPIRED")
    except Exception as exc:                     # keep the server healthy
        run.update(state="error", error="%s: %s" % (exc.__class__.__name__, exc))
    finally:
        db.close()
    return run
