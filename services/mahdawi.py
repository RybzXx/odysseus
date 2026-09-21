"""
services/mahdawi.py — the Platforms module logic, over the host DB.

Reuses the vendored stateless engines (mahdawi.content for price+caption,
mahdawi.fedshi for extraction+media) and keeps all state in one SQLAlchemy
model, MahdawiPost. Nothing here posts to a platform: a human approves, then
packaging builds a folder to post by hand.

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
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from core.database import MahdawiPost, SessionLocal, utcnow_naive
from mahdawi.content import compose
from mahdawi.content.models import FLAG_NO_MEDIA, FLAG_NO_PRICE
from mahdawi.fedshi.models import ProductRecord

STATUS_STAGED = "staged"
STATUS_APPROVED = "approved"
STATUS_PACKAGED = "packaged"
STATUS_POSTED = "posted"

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
    counts = {STATUS_STAGED: 0, STATUS_APPROVED: 0, STATUS_PACKAGED: 0, STATUS_POSTED: 0}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    from mahdawi.fedshi import session as fedshi_session
    return {
        "gathered": len(rows),
        "counts": counts,
        "fedshi_session": fedshi_session.has_state(),
        "channels": ["instagram", "tiktok", "fedshi"],
    }


# -- stage (no network) ------------------------------------------------------
def stage_records(db: Session, records: List[ProductRecord],
                  media_by_sku: Optional[Dict[str, List[str]]] = None,
                  owner: Optional[str] = None) -> dict:
    """
    Compose each record and persist a MahdawiPost. No network.

    Pre : records already fetched; media_by_sku maps sku -> local media paths.
    Post: each new sku has a staged row; duplicates skip; no-price/no-media flag.
    """
    media_by_sku = media_by_sku or {}
    staged, skipped, flagged = 0, 0, []
    for record in records:
        if get_post(db, record.sku, owner):
            skipped += 1
            continue
        paths = media_by_sku.get(record.sku, [])
        draft = compose.build_draft(record, media_paths=paths)
        row = MahdawiPost(
            id=str(uuid.uuid4()), owner=owner, sku=record.sku, title=draft.title,
            caption=draft.caption, price=draft.price, profit=draft.profit,
            media_dir=os.path.join(media_root(), record.sku),
            media_files=[os.path.basename(p) for p in draft.media_paths],
            channels=list(draft.target_channels), flags=list(draft.flags),
            status=STATUS_STAGED,
            fedshi_url=record.source_url or (_FEDSHI_PRODUCT_URL % record.sku),
            thumb_url=(record.image_urls[0] if record.image_urls else None),
        )
        db.add(row)
        staged += 1
        if FLAG_NO_PRICE in draft.flags or FLAG_NO_MEDIA in draft.flags:
            flagged.append(record.sku)
    db.commit()
    return {"staged": staged, "skipped_duplicate": skipped, "flagged": flagged}


# -- lifecycle ---------------------------------------------------------------
class NotFound(RuntimeError):
    pass


class BadState(RuntimeError):
    pass


def approve(db: Session, sku: str, owner: Optional[str] = None) -> dict:
    row = get_post(db, sku, owner)
    if not row:
        raise NotFound(sku)
    if row.status != STATUS_STAGED:
        raise BadState("sku %s is %s, not staged" % (sku, row.status))
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


def mark_posted(db: Session, sku: str, owner: Optional[str] = None) -> dict:
    row = get_post(db, sku, owner)
    if not row:
        raise NotFound(sku)
    row.status = STATUS_POSTED
    db.commit()
    return post_to_dict(row)


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

        report = stage_records(db, records, media_by_sku, owner)
        run.update(state="done", staged=report["staged"],
                   skipped=report["skipped_duplicate"], flagged=report["flagged"])
    except SessionExpired:
        run.update(state="error", error="SESSION_EXPIRED")
    except Exception as exc:                     # keep the server healthy
        run.update(state="error", error="%s: %s" % (exc.__class__.__name__, exc))
    finally:
        db.close()
    return run
