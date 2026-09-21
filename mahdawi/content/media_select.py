"""
content.media_select — order the downloaded media for a post.

Video leads, images follow, capped at the carousel max. Only files that exist
on disk (P2 verified and saved them) are included, so a PostDraft never points
at a missing file (spec 3.3.2).
"""
from __future__ import annotations

import os
from typing import List, Optional

from mahdawi.content import settings


def order_media(media_paths: List[str], cap: Optional[int] = None) -> List[str]:
    """
    Video files first, then images, capped.

    Pre : paths point at files P2 downloaded.
    Post: existing files only; length <= cap; a .mp4/.mov precedes images.
    """
    cap = settings.MEDIA_CAP if cap is None else cap
    existing = [p for p in media_paths if os.path.isfile(p)]
    videos = [p for p in existing if os.path.splitext(p)[1].lower() in (".mp4", ".mov")]
    images = [p for p in existing if p not in videos]
    return (videos + images)[:cap]
