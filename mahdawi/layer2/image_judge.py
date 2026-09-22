"""
layer2.image_judge — Gemini looks at each product image before it is posted.

Runs after content.media_check, so every image here is a readable file of a
postable size. Gemini answers the questions code cannot: does the image show
the product named in the title, and does it carry another shop's logo,
watermark, phone number, or foreign-language price tag.

Videos are not sent: Layer One's file check is their only check.
"""
from __future__ import annotations

import base64
import os
from typing import Any, List, Optional, Tuple

from mahdawi.content.media_check import is_video
from mahdawi.fedshi.models import ProductRecord
from mahdawi.layer2 import settings, voice
from mahdawi.layer2.gateway import Gateway

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".webp": "image/webp", ".gif": "image/gif"}

_TASK = """\
Check this product image before an Iraqi shop posts it. The product title is:
{title}
Reject the image if ANY of these is true:
- it does not show the product named in the title;
- it shows another shop's logo, watermark, handle, phone number, or website;
- it shows a price tag or price text;
- it is mainly a collage of unrelated items, or it is blurred beyond use.
Answer with JSON only: {{"ok": true|false, "reasons": ["<short reason in English>"]}}
When ok is false, give at least one reason.
"""


def check_verdict(data: Any) -> Optional[str]:
    """Post: None when data is {ok: bool, reasons: [str]} and a refusal names a reason."""
    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
        return "verdict has no boolean ok"
    reasons = data.get("reasons", [])
    if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
        return "reasons is not a list of text"
    if data["ok"] is False and not [r for r in reasons if r.strip()]:
        return "a rejection with no reason"
    return None


def _image_message(path: str, title: str) -> dict:
    mime = _MIME.get(os.path.splitext(path)[1].lower(), "image/jpeg")
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return {"role": "user", "content": [
        {"type": "text", "text": _TASK.format(title=title)},
        {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (mime, encoded)}},
    ]}


def judge_image(gateway: Gateway, record: ProductRecord, path: str) -> Tuple[bool, List[str]]:
    """
    Pre : path passed content.media_check and is an image.
    Post: (ok, reasons) from a checked verdict.
    Raises: Layer2Failure — the product waits for Layer Two.
    """
    msgs = [voice.system_message(), _image_message(path, record.title or record.sku)]
    data = gateway.complete_json(settings.MODEL_JUDGE, msgs, check_verdict,
                                 temperature=0.0)
    return data["ok"], [r.strip() for r in data.get("reasons", []) if r.strip()]


def filter_images(gateway: Gateway, record: ProductRecord, paths: List[str],
                  limit: Optional[int] = None) -> Tuple[List[str], List[Tuple[str, str]]]:
    """
    Pre : paths are in post order.
    Post: (kept, dropped). Videos pass through unjudged; each image is kept
          only when Gemini accepted it. Input order is preserved. With a limit,
          judging stops once kept holds limit files: files past that point
          could not be posted, so they cost no Gemini call and appear in
          neither list.
    Raises: Layer2Failure on the first image Gemini could not judge, so a
          half-judged set is never staged.
    """
    kept: List[str] = []
    dropped: List[Tuple[str, str]] = []
    for p in paths:
        if limit is not None and len(kept) >= limit:
            break
        if is_video(p):
            kept.append(p)
            continue
        ok, reasons = judge_image(gateway, record, p)
        if ok:
            kept.append(p)
        else:
            dropped.append((os.path.basename(p), "; ".join(reasons)))
    return kept, dropped
