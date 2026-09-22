"""
mahdawi.driver.instagram — post one packaged product to Instagram by driving the app.

The step order is fixed (it is the app's own flow); the brittle part — which
control each step taps — comes from selectors/instagram.json, resolved live
from a UiAutomator dump. Every required step that cannot resolve aborts the run
(fail closed). dry_run walks the whole flow and confirms the Share button is
reachable, but never taps it, so the loop is provable without a live post.

Instagram takes its image from the gallery picker, which shows the newest item
first, so this driver must make the pushed image newest and then prove that the
picker selected it. Everything that is not Instagram-specific lives in app_flow.

Contract:
  Pre : package_dir holds a caption file and at least one image; the phone is
        awake, the app is installed and logged in, and its runtime permissions
        are already granted (spec 6.2).
  Post: dry_run -> {"status": "dry_run_ready"} with Share resolved, nothing posted.
        live    -> {"status": "posted"} after the Share tap.
  Invariant: the home keyboard is restored even when a step raises.
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional

from mahdawi.driver import uinode
from mahdawi.driver.adb import ADBKEYBOARD_IME
from mahdawi.driver.app_flow import (  # noqa: F401  (re-exported for callers)
    AppDriver, first_image, load_selectors, read_package, storage_path,
)
from mahdawi.driver.errors import DriverError

CHANNEL = "instagram"

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


class InstagramDriver(AppDriver):
    def __init__(self, adb=None, selectors=None, home_ime=None, settle: float = 2.5):
        super().__init__(CHANNEL, adb=adb, selectors=selectors, home_ime=home_ime,
                         settle=settle)

    def _require_newest_in_gallery(self, remote: str) -> None:
        """
        Pre : the image is in MediaStore.
        Post: it is the newest image or video there, which is what the picker
              shows first.
        Raises: DriverError when another item is newer.
        """
        want = storage_path(remote)
        newest = self.adb.newest_gallery_item()
        if newest != want:
            raise DriverError("pushed image is not the newest gallery item (newest: %s)"
                              % newest)
        self.steps.append("pushed image is newest in the gallery")

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
        added = self.adb.date_added(storage_path(remote))
        if got is None or added is None:
            raise DriverError("cannot confirm the selected photo (tile %r, date_added %r)"
                              % (tile.desc if tile else None, added))
        want = local_minute(added, self.adb.utc_offset_seconds())
        if got != want:
            raise DriverError("Instagram selected another photo: created %s, pushed %s"
                              % (got, want))
        self.steps.append("selected photo is the pushed image")

    # -- the flow ------------------------------------------------------------
    def post(self, package_dir: str, dry_run: bool = True) -> dict:
        caption, media = read_package(package_dir, CHANNEL)
        target = first_image(media)       # single image this slice; carousel later
        sku = os.path.basename(os.path.normpath(package_dir))
        remote = self.remote_name(sku, target)
        try:
            self._push_to_gallery(target, remote)
            self._require_newest_in_gallery(remote)
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
            self._type_into("caption_field", caption)

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
