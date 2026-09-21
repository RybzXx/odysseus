"""
mahdawi.driver.instagram — post one packaged product to Instagram by driving the app.

The step order is fixed (it is the app's own flow); the brittle part — which
control each step taps — comes from selectors/instagram.json, resolved live
from a UiAutomator dump. Every required step that cannot resolve aborts the run
(fail closed). dry_run walks the whole flow and confirms the Share button is
reachable, but never taps it, so the loop is provable without a live post.

Contract:
  Pre : package_dir holds caption.txt and at least one media file; the phone is
        awake, the app is installed and logged in, and its runtime permissions
        are already granted (spec 6.2).
  Post: dry_run -> {"status": "dry_run_ready"} with Share resolved, nothing posted.
        live    -> {"status": "posted"} after the Share tap.
  Invariant: the home keyboard is restored even when a step raises.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import List, Optional

from mahdawi.driver import uinode
from mahdawi.driver.adb import ADBKEYBOARD_IME, Adb
from mahdawi.driver.errors import DriverError

_SELECTORS_DIR = os.path.join(os.path.dirname(__file__), "selectors")
_HOME_IME_DEFAULT = "com.samsung.android.honeyboard/.service.HoneyBoardService"
_REMOTE_MEDIA_DIR = "/sdcard/Pictures/mahdawi"
_MEDIA_EXT = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov")


def load_selectors(app: str = "instagram") -> dict:
    with open(os.path.join(_SELECTORS_DIR, "%s.json" % app), encoding="utf-8") as f:
        return json.load(f)


def _read_package(package_dir: str) -> tuple:
    """
    Pre : package_dir exists. Post: (caption_text, [media_paths]) — media in
          name order, caption.txt/meta.json excluded. Raises DriverError when
          the caption or all media are missing.
    """
    cap_path = os.path.join(package_dir, "caption.txt")
    if not os.path.isfile(cap_path):
        raise DriverError("package has no caption.txt: %s" % package_dir)
    caption = open(cap_path, encoding="utf-8").read()
    media = sorted(
        os.path.join(package_dir, n) for n in os.listdir(package_dir)
        if n.lower().endswith(_MEDIA_EXT))
    if not media:
        raise DriverError("package has no media: %s" % package_dir)
    return caption, media


class InstagramDriver:
    def __init__(self, adb: Optional[Adb] = None, selectors: Optional[dict] = None,
                 home_ime: Optional[str] = None, settle: float = 2.5):
        self.adb = adb or Adb()
        self.sel = selectors or load_selectors("instagram")
        self.home_ime = home_ime or os.environ.get("MAHDAWI_HOME_IME", _HOME_IME_DEFAULT)
        self.settle = settle          # seconds to let a screen transition land
        self.steps: List[str] = []

    # -- resolution ----------------------------------------------------------
    def _screen_size(self) -> tuple:
        out = self.adb.shell("wm", "size")
        m = re.search(r"(\d+)x(\d+)", out)
        if not m:
            raise DriverError("cannot read screen size: %r" % out)
        return int(m.group(1)), int(m.group(2))

    def _has_element_criteria(self, key: str) -> bool:
        spec = self.sel[key]
        return any(k in spec for k in
                   ("rid", "desc", "text", "texts", "descs", "class_contains"))

    def _resolve(self, key: str, retries: int = 6, delay: float = 0.7):
        if not self._has_element_criteria(key):
            return None                      # fallback-only control; nothing to find
        selector = uinode.Selector.from_map(self.sel[key])
        for _ in range(retries):
            node = uinode.find(self.adb.ui_xml(), selector)
            if node:
                return node
            time.sleep(delay)
        return None

    def _open_create(self, taps: int = 3) -> None:
        """
        Tap the create control until the select screen appears (its Next shows).

        Retries because a just-launched app can swallow the first tap. Raises
        DriverError when New post never opens.
        """
        for _ in range(taps):
            self._tap("create_button")
            self._wait()
            if self._resolve("next", retries=4):
                return
        raise DriverError("New post did not open")

    def _tap(self, key: str, required: bool = True) -> bool:
        node = self._resolve(key)
        if node:
            x, y = node.center()
            self.adb.tap(x, y)
            self.steps.append("tap %s @%d,%d" % (key, x, y))
            return True
        spec = self.sel[key]
        if "fallback_xy" in spec:
            w, h = self._screen_size()
            fx, fy = spec["fallback_xy"]
            x, y = int(w * fx), int(h * fy)
            self.adb.tap(x, y)
            self.steps.append("tap %s @fallback %d,%d" % (key, x, y))
            return True
        if required:
            raise DriverError("required control %r not found" % key)
        self.steps.append("skip %s (absent)" % key)
        return False

    def _wait(self):
        time.sleep(self.settle)

    # -- the flow ------------------------------------------------------------
    def post(self, package_dir: str, dry_run: bool = True) -> dict:
        caption, media = _read_package(package_dir)
        target = media[0]                 # single image this slice; carousel later
        sku = os.path.basename(os.path.normpath(package_dir))
        remote = "%s/%s_%s" % (_REMOTE_MEDIA_DIR, sku, os.path.basename(target))

        self.adb.shell("mkdir", "-p", _REMOTE_MEDIA_DIR)
        self.adb.push(target, remote)
        self.adb.media_scan(remote)
        self.steps.append("push %s" % os.path.basename(remote))

        self.adb.set_ime(ADBKEYBOARD_IME)
        try:
            self.adb.launch(self.sel["app_package"])
            self._wait()
            self._open_create()                        # New post select screen ready
            self._tap("next"); self._wait()            # select -> edit (image auto-selected)
            self._tap("audio_remove", required=False)   # photo posts usually have none
            self._tap("next"); self._wait()            # edit -> caption
            self._tap("sharing_ok", required=False); self._wait()  # first-post dialog, maybe

            field = self._resolve("caption_field")
            if not field:
                raise DriverError("caption field not found")
            x, y = field.center()
            self.adb.tap(x, y)
            time.sleep(0.8)
            self.adb.type_text(caption)
            self.steps.append("typed caption (%d chars)" % len(caption))
            time.sleep(1.0)

            share = self._resolve("share_button")
            if not share:
                raise DriverError("share button not reachable")

            if dry_run:
                self.steps.append("dry_run: Share reachable, not tapped")
                return {"status": "dry_run_ready", "sku": sku, "steps": self.steps}

            sx, sy = share.center()
            self.adb.tap(sx, sy)
            self.steps.append("tapped Share")
            self._wait()
            return {"status": "posted", "sku": sku, "steps": self.steps}
        finally:
            self.adb.set_ime(self.home_ime)
