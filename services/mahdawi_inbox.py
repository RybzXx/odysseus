"""
services/mahdawi_inbox.py — customer messages for the Platforms module.

Joins the messaging pipeline (mahdawi.messaging) to Odysseus: the shop facts
come from app.db, the Gemini agents from the 9router gateway, and the ledger
lives in its own SQLite file (messaging.settings.DB_PATH).

run_inbox needs a channel adapter. The Instagram DM adapter over ADB is not
built yet, so no route calls run_inbox today; the approval queue is readable.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from core.database import MahdawiPost
from mahdawi.content import settings as content_settings
from mahdawi.layer2.replies import GeminiClassifier, GeminiReplyWriter
from mahdawi.messaging import runner, store
from mahdawi.messaging.models import RunReport, ShopFacts
from services import mahdawi as posts

# Products a customer can order: approved, packaged, or already posted.
_ORDERABLE = (posts.STATUS_APPROVED, posts.STATUS_PACKAGED, posts.STATUS_POSTED)


def shop_facts(db: Session, owner: Optional[str] = None) -> ShopFacts:
    """
    Post: the facts a reply may state — delivery, payment, and how to order,
          plus each orderable product's title and code-set price.
    """
    q = db.query(MahdawiPost).filter(MahdawiPost.status.in_(_ORDERABLE),
                                     MahdawiPost.price.isnot(None))
    if owner is not None:
        q = q.filter(MahdawiPost.owner == owner)
    products = tuple((r.title or r.sku, int(r.price)) for r in q.all())
    lines = (("delivery_and_payment", content_settings.TRUST_LINE),
             ("how_to_order", content_settings.ORDER_CTA_DM))
    return ShopFacts(lines=lines, products=products)


def run_inbox(db: Session, channel, owner: Optional[str] = None,
              db_path: Optional[str] = None) -> RunReport:
    """
    One pass over one channel.

    Pre : Layer Two is on (a gateway exists).
    Post: every ingested item holds exactly one terminal state.
    """
    gateway = posts.layer2_gateway(db)
    if gateway is None:
        raise RuntimeError("Layer Two is off; replies are written only by Gemini")
    conn = store.connect(db_path)
    try:
        return runner.run(conn, channel, GeminiClassifier(gateway),
                          GeminiReplyWriter(gateway), shop_facts(db, owner))
    finally:
        conn.close()


def pending_replies(db_path: Optional[str] = None) -> List[dict]:
    """Post: staged replies not yet approved, oldest first, for the dashboard."""
    conn = store.connect(db_path)
    try:
        return store.staged_rows(conn, approved=False)
    finally:
        conn.close()
