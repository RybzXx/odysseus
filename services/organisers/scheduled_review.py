"""Running the review pass on its own schedule, for every owner who enabled it.

Kept apart from ``review`` so that module stays about one pass over one owner's
mail, and this one about when passes happen and for whom.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from sqlalchemy import or_

from core.database import SessionLocal, WorkOrganiser
from services.organisers.review import ReviewUnavailable, run_review_pass

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_HOURS = 24
MIN_INTERVAL_SECONDS = 3600

# One pass at a time across the whole process. Two concurrent passes over the
# same mail would ask the same question twice and pay for it twice.
_pass_lock = asyncio.Lock()


def review_interval_seconds() -> int:
    """How long to wait before the next round of passes.

    Post: at least an hour, whatever the setting says. A shorter cadence would
          spend tokens faster than a person can work the queue it fills.
    """
    try:
        from src.settings import get_setting

        hours = int(get_setting("organiser_review_interval_hours", DEFAULT_INTERVAL_HOURS)
                    or DEFAULT_INTERVAL_HOURS)
    except Exception:
        hours = DEFAULT_INTERVAL_HOURS
    return max(MIN_INTERVAL_SECONDS, hours * 3600)


def _owners_with_review_enabled(db) -> List[Optional[str]]:
    """The owners whose settings switch the pass on.

    Post: one entry per distinct organiser owner that has enabled the pass.
          An owner with no organisers is skipped -- there is nothing to review.
    """
    from src.settings import get_user_setting, load_settings

    settings = load_settings()
    owners = [
        row[0] for row in
        db.query(WorkOrganiser.owner).filter(WorkOrganiser.is_active == True).distinct().all()
    ]

    enabled = []
    for owner in owners:
        try:
            if get_user_setting("organiser_review_enabled", owner or "",
                                settings.get("organiser_review_enabled", False)):
                enabled.append(owner)
        except Exception:
            continue
    return enabled


async def run_scheduled_review() -> dict:
    """Run one pass for each owner who has the review switched on.

    Pre:  none. An owner with the pass off, or misconfigured, is skipped.
    Post: a summary keyed by owner. A failure for one owner is logged and does
          not stop the others.
    Inv:  no categorisation changes here. The pass only opens contests, and a
          human resolves those.
    """
    if _pass_lock.locked():
        logger.debug("Organiser review already running; skipping this round")
        return {"skipped": "a pass is already running"}

    async with _pass_lock:
        db = SessionLocal()
        try:
            owners = _owners_with_review_enabled(db)
            if not owners:
                return {}

            from routes.organisers.organisers_routes import (
                _get_recent_emails,
                load_organiser_overrides,
            )

            summaries = {}
            for owner in owners:
                try:
                    emails = await asyncio.to_thread(_get_recent_emails, 14)
                    if not emails:
                        continue
                    organisers = db.query(WorkOrganiser).filter(
                        or_(WorkOrganiser.owner == owner, WorkOrganiser.owner == None),
                        WorkOrganiser.is_active == True,
                    ).all()
                    overrides = load_organiser_overrides(db, owner)
                    summaries[owner or ""] = await run_review_pass(
                        db, owner, emails, organisers, overrides,
                    )
                except ReviewUnavailable as e:
                    # A configuration fault for this owner alone.
                    logger.info("Organiser review skipped for %s: %s", owner, e)
                except Exception as e:
                    logger.warning("Organiser review failed for %s: %s", owner, e)
            return summaries
        finally:
            db.close()
