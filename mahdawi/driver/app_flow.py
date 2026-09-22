"""
mahdawi.driver.app_flow — what every app driver needs before its own flow starts.

One package, one image, one phone. The parts that do not depend on which app
posts live here: reading the package, putting the image where the app can find
it, waiting for the app to own the screen, resolving and tapping controls, and
cleaning up after a failure.

AppDriver holds no flow. InstagramDriver and TikTokDriver each add their own,
because the step order IS the app, and those two apps differ: Instagram picks
the newest gallery item, TikTok takes the image through a share intent.

Contract for a subclass:
  Pre : the package holds a caption file and at least one image; the phone is
        awake, the app is installed and logged in, and its permissions are granted.
  Post: dry_run -> the post screen is ready and nothing is published.
        live    -> the post button is tapped exactly once.
  Invariant: the home keyboard comes back even when a step raises.
"""
from __future__ import annotations

import json
import os
import time
from typing import List, Optional

from mahdawi.driver import uinode
from mahdawi.driver.adb import Adb
from mahdawi.driver.errors import DriverError

SELECTORS_DIR = os.path.join(os.path.dirname(__file__), "selectors")
HOME_IME_DEFAULT = "com.samsung.android.honeyboard/.service.HoneyBoardService"
REMOTE_MEDIA_DIR = "/sdcard/Pictures/mahdawi"
MEDIA_EXT = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")

SCAN_WAIT_SECONDS = 30
LAUNCH_WAIT_SECONDS = 30


def load_selectors(app: str) -> dict:
    with open(os.path.join(SELECTORS_DIR, "%s.json" % app), encoding="utf-8") as f:
        return json.load(f)


def read_package(package_dir: str, channel: str) -> tuple:
    """
    Pre : package_dir exists; channel names the target platform.
    Post: (caption_text, [media_paths]). The channel's own caption file wins
          over the shared caption.txt, because each channel has its own hashtag
          cap. Media follow meta.json's "media" order — the post order the
          pipeline chose — and fall back to name order without meta.json.
    Raises: DriverError when the caption or all media are missing.
    """
    cap_path = os.path.join(package_dir, "caption_%s.txt" % channel)
    if not os.path.isfile(cap_path):
        cap_path = os.path.join(package_dir, "caption.txt")
    if not os.path.isfile(cap_path):
        raise DriverError("package has no caption.txt: %s" % package_dir)
    caption = open(cap_path, encoding="utf-8").read()

    names = None
    meta_path = os.path.join(package_dir, "meta.json")
    if os.path.isfile(meta_path):
        names = json.load(open(meta_path, encoding="utf-8")).get("media")
    if not names:
        names = sorted(os.listdir(package_dir))
    media = [os.path.join(package_dir, n) for n in names
             if n.lower().endswith(MEDIA_EXT) and os.path.isfile(os.path.join(package_dir, n))]
    if not media:
        raise DriverError("package has no media: %s" % package_dir)
    return caption, media


def first_image(media: List[str]) -> str:
    """
    Post: the first image in post order. Both drivers post one photo, so a
          video must never enter the photo flow.
    Raises: DriverError when the package holds no image.
    """
    for path in media:
        if path.lower().endswith(IMAGE_EXT):
            return path
    raise DriverError("package has no image; video posts are not supported yet")


def storage_path(remote: str) -> str:
    """/sdcard/... as MediaStore records it: /storage/emulated/0/..."""
    if remote.startswith("/sdcard/"):
        return "/storage/emulated/0/" + remote[len("/sdcard/"):]
    return remote


class AppDriver:
    def __init__(self, app: str, adb: Optional[Adb] = None,
                 selectors: Optional[dict] = None, home_ime: Optional[str] = None,
                 settle: float = 2.5):
        self.app = app
        self.adb = adb or Adb()
        self.sel = selectors or load_selectors(app)
        self.home_ime = home_ime or os.environ.get("MAHDAWI_HOME_IME", HOME_IME_DEFAULT)
        self.settle = settle          # seconds to let a screen transition land
        self.steps: List[str] = []

    # -- resolution ----------------------------------------------------------
    def _screen_size(self) -> tuple:
        import re
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

    def _tap(self, key: str, required: bool = True, retries: int = 6) -> bool:
        node = self._resolve(key, retries=retries)
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

    # -- phone state ---------------------------------------------------------
    def _launch_and_wait(self) -> None:
        """
        Start the app and wait until it owns the screen.

        A fixed settle is not enough: after the owner changed Instagram's photo
        permission the app was force-stopped, its first start ran long, and the
        driver tapped into Termux instead (bug 11). Every tap is blind, so the
        app must hold the focus before the first one.

        Post: the focused window belongs to the app package.
        Raises: DriverError when it does not within LAUNCH_WAIT_SECONDS.
        """
        package = self.sel["app_package"]
        self.adb.launch(package)
        self._await_front(package)

    def _await_front(self, package: str) -> None:
        deadline = time.time() + LAUNCH_WAIT_SECONDS
        front = None
        while time.time() < deadline:
            front = self.adb.foreground_package()
            if front == package:
                self.steps.append("%s is in front" % package)
                return
            time.sleep(1.0)
        raise DriverError("%s did not come to the front within %ds (front: %s)"
                          % (package, LAUNCH_WAIT_SECONDS, front))

    def remote_name(self, sku: str, target: str) -> str:
        """
        Post: a per-run name under REMOTE_MEDIA_DIR. Re-pushing an existing name
              keeps its old date_added, and Instagram's picker reads that order.
        """
        return "%s/%s_%d_%s" % (REMOTE_MEDIA_DIR, sku, int(time.time()),
                                os.path.basename(target))

    def _push_to_gallery(self, target: str, remote: str) -> int:
        """
        Copy the image to the phone and wait until MediaStore holds it.

        The scan is asynchronous: on 2026-09-22 a row appeared 64 s after the
        push, long after the app had read the gallery.

        Post: MediaStore holds the file; returns its media id.
        Raises: DriverError when no row appears within SCAN_WAIT_SECONDS.
        """
        self.adb.shell("mkdir", "-p", REMOTE_MEDIA_DIR)
        self.adb.push(target, remote)
        self.adb.touch(remote)             # date_modified = now, not the PC's mtime
        want = storage_path(remote)
        deadline = time.time() + SCAN_WAIT_SECONDS
        while time.time() < deadline:
            self.adb.media_scan(remote)
            media_id = self.adb.media_id(want)
            if media_id is not None:
                self.steps.append("push %s (media id %d)" % (os.path.basename(remote), media_id))
                return media_id
            time.sleep(1.0)
        raise DriverError("MediaStore did not index %s within %ds"
                          % (os.path.basename(remote), SCAN_WAIT_SECONDS))

    def _drop_from_gallery(self, remote: str) -> None:
        """
        Remove the image this run pushed. Never raises: the run already failed,
        and a failed cleanup must not replace the real error.
        """
        try:
            self.adb.delete_media(storage_path(remote))
            self.steps.append("removed %s from the gallery" % os.path.basename(remote))
        except DriverError:
            self.steps.append("could not remove %s" % os.path.basename(remote))

    def _type_into(self, key: str, text: str, retries: int = 6) -> None:
        """
        Pre : the field named by key is on screen, or arrives within retries.
        Post: the field holds text, typed through ADBKeyboard.
        Raises: DriverError when the field does not resolve.
        """
        field = self._resolve(key, retries=retries)
        if not field:
            raise DriverError("%s not found" % key)
        x, y = field.center()
        self.adb.tap(x, y)
        time.sleep(0.8)
        self.adb.type_text(text)
        self.steps.append("typed %s (%d chars)" % (key, len(text)))
        time.sleep(1.0)
