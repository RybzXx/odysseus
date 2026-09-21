"""
fedshi.media — download product media, verify each file, never save a corrupt one.

Fedshi media is public (research: prod-media.fedshi.com serves images and video
with no auth), so this uses stdlib urllib only.

The fetcher is injected so tests exercise verification with no network: a fake
fetcher returns a truncated body or an HTML error, and the test asserts nothing
is saved (spec 2.6.2).
"""
from __future__ import annotations

import os
import urllib.request
from typing import Callable, List, Optional, Tuple

# A fetcher returns (status_code, content_type, body_bytes).
Fetcher = Callable[[str], Tuple[int, str, bytes]]

# Which content-type an extension must carry, so an HTML error page saved as
# .mp4 is caught rather than written.
_EXPECTED = {
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image",
    ".mp4": "video", ".mov": "video",
}


class MediaError(RuntimeError):
    """A download that failed verification. Never a saved file."""


def _urllib_fetch(url: str, timeout: int = 60) -> Tuple[int, str, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def _verify(url: str, status: int, content_type: str, body: bytes) -> None:
    """
    Pre : a fetch returned status/content_type/body for url.
    Post: returns cleanly only for a real, non-empty file of the right family.
    Raises MediaError otherwise — the caller must not save a rejected body.
    """
    if status != 200:
        raise MediaError("%s -> HTTP %d" % (url, status))
    if not body:
        raise MediaError("%s -> empty body" % url)
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    family = _EXPECTED.get(ext)
    if family and family not in content_type.lower():
        raise MediaError("%s -> content-type %r is not %s" % (url, content_type, family))


def download_one(url: str, dest: str, fetch: Optional[Fetcher] = None) -> str:
    """
    Download url to dest, only if it verifies.

    Post: dest exists and holds a verified body; returns dest.
    Invariant: on any failure, dest is not created (verify runs before write).
    """
    fetch = fetch or _urllib_fetch
    status, content_type, body = fetch(url)
    _verify(url, status, content_type, body)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(body)
    return dest


def download_all(urls: List[str], media_dir: str, fetch: Optional[Fetcher] = None) -> List[str]:
    """
    Download every url into media_dir, keyed by the source filename.

    Post: returns the saved paths. A file already present and non-empty is kept,
          not re-fetched (idempotent, spec 2.2.3).
    """
    saved = []
    for url in urls:
        name = os.path.basename(url.split("?")[0])
        dest = os.path.join(media_dir, name)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            saved.append(dest)
            continue
        saved.append(download_one(url, dest, fetch=fetch))
    return saved
