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


_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
_SCAN_WAIT_SECONDS = 30
_LAUNCH_WAIT_SECONDS = 30


def _read_package(package_dir: str) -> tuple:
    """
    Pre : package_dir exists.
    Post: (caption_text, [media_paths]). Media follow meta.json's "media" order —
          the post order the pipeline chose — and fall back to name order for a
          package without meta.json. The Instagram caption file wins over the
          shared caption.txt when the package has one.
    Raises: DriverError when the caption or all media are missing.
    """
    cap_path = os.path.join(package_dir, "caption_instagram.txt")
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
             if n.lower().endswith(_MEDIA_EXT) and os.path.isfile(os.path.join(package_dir, n))]
    if not media:
        raise DriverError("package has no media: %s" % package_dir)
    return caption, media


def first_image(media: List[str]) -> str:
    """
    Post: the first image in post order. This slice posts one photo, so a video
          must never enter the photo flow.
    Raises: DriverError when the package holds no image.
    """
    for path in media:
        if path.lower().endswith(_IMAGE_EXT):
            return path
    raise DriverError("package has no image; video posts are not supported yet")


_MONTHS = ("january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december")
_CREATED = re.compile(r"created on (\d{1,2}) ([A-Za-z]+) (\d{4}) (\d{1,2}):(\d{2})")


def selected_photo_minute(desc: str) -> Optional[tuple]:
    """
    Pre : desc is the selected tile's content-desc, English UI, e.g.
          "Selected Photo thumbnail created on 20 September 2026 18:35".
    Post: (year, month, day, hour, minute) in phone-local time, or None when
          the text does not parse — the caller then fails closed.
    """
    m = _CREATED.search(desc or "")
    if not m or m.group(2).lower() not in _MONTHS:
        return None
    day, month_name, year, hour, minute = m.groups()
    return (int(year), _MONTHS.index(month_name.lower()) + 1, int(day), int(hour), int(minute))


def local_minute(epoch: int, utc_offset: int) -> tuple:
    """Post: (year, month, day, hour, minute) of epoch at the given UTC offset."""
    t = time.gmtime(epoch + utc_offset)
    return (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min)


def _storage_path(remote: str) -> str:
    """/sdcard/... as MediaStore records it: /storage/emulated/0/..."""
    if remote.startswith("/sdcard/"):
        return "/storage/emulated/0/" + remote[len("/sdcard/"):]
    return remote


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
        Reach the New post select screen, whatever screen the app resumed on.

        The create control is a fixed position, and that position means two
        things: on Home it opens the photo picker, on Profile it opens the
        Create sheet (Reel / Edits / Post / …). On 2026-09-22 Instagram resumed
        on Profile and the run died as "New post did not open" (bug 9). So each
        attempt goes to Home first, taps create, and taps the sheet's Post row
        when that sheet is what appeared.

        Post: the select screen is open (its Next resolves).
        Raises: DriverError when it is not, after `taps` attempts.
        """
        for _ in range(taps):
            if self._resolve("next", retries=1):
                return                         # already on the select screen
            self._tap("home_tab", required=False)
            self._wait()
            self._tap("create_button")
            self._wait()
            if self._tap("create_post_option", required=False):
                self._wait()                   # the Create sheet was open
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

    def _stage_in_gallery(self, target: str, remote: str) -> None:
        """
        Put the post image first in the phone's gallery.

        The New post screen auto-selects the newest gallery item, so the image
        must be indexed AND newest before the app opens. On 2026-09-22 the scan
        landed 64 s after the push, the picker selected an older image, and a
        dry run still reported ready (bug 7).

        Post: MediaStore's newest image or video is remote.
        Raises: DriverError when that does not hold within _SCAN_WAIT_SECONDS.
        """
        self.adb.shell("mkdir", "-p", _REMOTE_MEDIA_DIR)
        self.adb.push(target, remote)
        self.adb.touch(remote)             # date_modified = now, not the PC's mtime
        want = _storage_path(remote)
        deadline = time.time() + _SCAN_WAIT_SECONDS
        newest = None
        while time.time() < deadline:
            self.adb.media_scan(remote)
            newest = self.adb.newest_gallery_item()
            if newest == want:
                self.steps.append("push %s (newest in gallery)" % os.path.basename(remote))
                return
            time.sleep(1.0)
        raise DriverError("pushed image is not the newest gallery item after %ds (newest: %s)"
                          % (_SCAN_WAIT_SECONDS, newest))

    def _check_selection(self, remote: str) -> None:
        """
        Confirm the New post screen selected the pushed image.

        The picker selects its first Recents item, and a newest-in-MediaStore
        file is not enough: with partial photo access Instagram sees only the
        files the owner once granted, so it selected the store logo while the
        product image sat unseen (2026-09-22).

        Pre : the select screen is open.
        Post: the selected tile's creation minute equals the pushed file's
              date_added minute in phone-local time.
        Raises: DriverError on partial access, on a missing or unreadable
              selected tile, or on a different photo — before any caption is typed.
        """
        xml = self.adb.ui_xml()
        if uinode.find(xml, uinode.Selector.from_map(self.sel["partial_access"])):
            raise DriverError("Instagram has partial photo access, so it cannot see the "
                              "pushed image. Allow all photos: Settings > Apps > "
                              "Instagram > Permissions > Photos and videos > Allow all")
        tile = uinode.find(xml, uinode.Selector.from_map(self.sel["selected_photo"]))
        got = selected_photo_minute(tile.desc if tile else "")
        added = self.adb.date_added(_storage_path(remote))
        if got is None or added is None:
            raise DriverError("cannot confirm the selected photo (tile %r, date_added %r)"
                              % (tile.desc if tile else None, added))
        want = local_minute(added, self.adb.utc_offset_seconds())
        if got != want:
            raise DriverError("Instagram selected another photo: created %s, pushed %s"
                              % (got, want))
        self.steps.append("selected photo is the pushed image")

    def _launch_and_wait(self) -> None:
        """
        Start the app and wait until it owns the screen.

        A fixed settle is not enough: after the owner changed Instagram's photo
        permission the app was force-stopped, its first start ran long, and the
        driver tapped into Termux instead (bug 11). Every tap is blind, so the
        app must hold the focus before the first one.

        Post: the focused window belongs to the app package.
        Raises: DriverError when it does not within _LAUNCH_WAIT_SECONDS.
        """
        package = self.sel["app_package"]
        self.adb.launch(package)
        deadline = time.time() + _LAUNCH_WAIT_SECONDS
        front = None
        while time.time() < deadline:
            front = self.adb.foreground_package()
            if front == package:
                self.steps.append("%s is in front" % package)
                return
            time.sleep(1.0)
        raise DriverError("%s did not come to the front within %ds (front: %s)"
                          % (package, _LAUNCH_WAIT_SECONDS, front))

    def _drop_from_gallery(self, remote: str) -> None:
        """
        Remove the image this run pushed. Never raises: the run already failed,
        and a failed cleanup must not replace the real error.
        """
        try:
            self.adb.delete_media(_storage_path(remote))
            self.steps.append("removed %s from the gallery" % os.path.basename(remote))
        except DriverError:
            self.steps.append("could not remove %s" % os.path.basename(remote))

    # -- the flow ------------------------------------------------------------
    def post(self, package_dir: str, dry_run: bool = True) -> dict:
        caption, media = _read_package(package_dir)
        target = first_image(media)       # single image this slice; carousel later
        sku = os.path.basename(os.path.normpath(package_dir))
        # A fresh name per run: re-pushing an existing name keeps its old
        # date_added, so the file would not become the newest item again.
        remote = "%s/%s_%d_%s" % (_REMOTE_MEDIA_DIR, sku, int(time.time()),
                                  os.path.basename(target))
        try:
            self._stage_in_gallery(target, remote)
        except DriverError:
            self._drop_from_gallery(remote)
            raise

        self.adb.set_ime(ADBKEYBOARD_IME)
        try:
            self._launch_and_wait()                    # the app owns the screen
            self._wait()
            self._open_create()                        # New post select screen ready
            self._check_selection(remote)              # the pushed image, or stop
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
        except DriverError:
            # The image reached the gallery but no post used it. Leaving it
            # there fills the picker's Recents with dead copies (bug 10). A
            # posted image stays: Instagram may still be uploading it.
            self._drop_from_gallery(remote)
            raise
        finally:
            self.adb.set_ime(self.home_ime)
