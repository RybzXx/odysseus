"""
content.media_check — Layer One's file checks on downloaded media.

Before Gemini looks at an image, code confirms the file is there, is an image
it can read the size of, is large enough to post, and is not a copy of another
file in the same set. These are facts about bytes, so they belong to code.

Sizes are read from the file header (PNG, JPEG, GIF, WebP) with the standard
library, so no imaging dependency is added.
"""
from __future__ import annotations

import hashlib
import os
import struct
from typing import List, Optional, Tuple

VIDEO_EXTS = (".mp4", ".mov")
MIN_IMAGE_SIDE = int(os.environ.get("MAHDAWI_MIN_IMAGE_SIDE", "320"))


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def image_size(path: str) -> Optional[Tuple[int, int]]:
    """Post: (width, height) from the header, or None when the format is unknown."""
    with open(path, "rb") as f:
        head = f.read(32)
        if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
            return struct.unpack(">II", head[16:24])
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", head[6:10])
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return _webp_size(head)
        if head[:2] == b"\xff\xd8":
            f.seek(2)
            return _jpeg_size(f)
    return None


def _webp_size(head: bytes) -> Optional[Tuple[int, int]]:
    chunk = head[12:16]
    if chunk == b"VP8X":
        w = int.from_bytes(head[24:27], "little") + 1
        h = int.from_bytes(head[27:30], "little") + 1
        return w, h
    if chunk == b"VP8 " and len(head) >= 30:
        w, h = struct.unpack("<HH", head[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L" and len(head) >= 25:
        b = head[21:25]
        w = 1 + (((b[1] & 0x3F) << 8) | b[0])
        h = 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
        return w, h
    return None


def _jpeg_size(f) -> Optional[Tuple[int, int]]:
    """Walk JPEG segments to the first start-of-frame marker."""
    while True:
        byte = f.read(1)
        while byte and byte != b"\xff":
            byte = f.read(1)
        while byte == b"\xff":
            byte = f.read(1)
        if not byte:
            return None
        marker = byte[0]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        length = f.read(2)
        if len(length) < 2:
            return None
        seg_len = struct.unpack(">H", length)[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            data = f.read(5)
            if len(data) < 5:
                return None
            h, w = struct.unpack(">HH", data[1:5])
            return w, h
        f.seek(seg_len - 2, 1)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def check_media(paths: List[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
    """
    Split media into files fit to post and files dropped, with a reason each.

    Post: kept preserves input order; every input appears in exactly one list.
          A video passes on existing and being non-empty; code cannot judge its
          frames, and Layer Two judges images only.
    """
    kept: List[str] = []
    dropped: List[Tuple[str, str]] = []
    seen = set()
    for p in paths:
        name = os.path.basename(p)
        if not os.path.isfile(p) or os.path.getsize(p) == 0:
            dropped.append((name, "missing or empty file"))
            continue
        digest = _sha256(p)
        if digest in seen:
            dropped.append((name, "duplicate of another file"))
            continue
        seen.add(digest)
        if is_video(p):
            kept.append(p)
            continue
        try:
            size = image_size(p)
        except (OSError, struct.error):
            size = None
        if size is None:
            dropped.append((name, "not a readable image"))
        elif min(size) < MIN_IMAGE_SIDE:
            dropped.append((name, "image %dx%d below %dpx" % (size[0], size[1], MIN_IMAGE_SIDE)))
        else:
            kept.append(p)
    return kept, dropped
