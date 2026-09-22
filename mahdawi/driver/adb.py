"""
mahdawi.driver.adb — a thin adb wrapper the driver uses to reach the phone.

Transport-agnostic: on a PC it targets the USB device; on the phone itself it
targets the local adbd. Configure with env MAHDAWI_ADB_BIN (default "adb") and
MAHDAWI_ADB_SERIAL (default: adb's own single-device pick).

No business logic lives here — just push a file, tap a point, type text through
ADBKeyboard, and read a UiAutomator dump.
"""
from __future__ import annotations

import base64
import os
import subprocess
from typing import List, Optional

from mahdawi.driver.errors import DriverError

ADBKEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"
_UI_DUMP_PATH = "/sdcard/mahdawi_ui.xml"


class Adb:
    def __init__(self, bin: Optional[str] = None, serial: Optional[str] = None,
                 timeout: int = 40):
        self.bin = bin or os.environ.get("MAHDAWI_ADB_BIN", "adb")
        self.serial = serial or os.environ.get("MAHDAWI_ADB_SERIAL") or None
        self.timeout = timeout

    def _base(self) -> List[str]:
        return [self.bin] + (["-s", self.serial] if self.serial else [])

    def _run(self, args: List[str], timeout: Optional[int] = None) -> str:
        """
        Post: stdout on rc 0. Raises DriverError on non-zero or on timeout, so a
        broken adb call aborts the run rather than passing silently.
        """
        cmd = self._base() + args
        try:
            # Decode as UTF-8 (the UI dump and Arabic captions are UTF-8); never
            # the Windows ANSI codepage, which chokes on those bytes.
            p = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=timeout or self.timeout)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise DriverError("adb call failed: %s" % exc)
        if p.returncode != 0:
            raise DriverError("adb %s -> rc %d: %s" % (args[:2], p.returncode, p.stderr.strip()))
        return p.stdout

    # -- device actions ------------------------------------------------------
    def shell(self, *args: str) -> str:
        return self._run(["shell", *args])

    def push(self, local: str, remote: str) -> None:
        if not os.path.isfile(local):
            raise DriverError("push source missing: %s" % local)
        self._run(["push", local, remote])

    def media_scan(self, remote: str) -> None:
        self.shell("am", "broadcast", "-a",
                   "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                   "-d", "file://%s" % remote)

    def touch(self, remote: str) -> None:
        """Post: the file's mtime is now. adb push keeps the PC file's mtime."""
        self.shell("touch", remote)

    def delete_media(self, storage_path: str) -> None:
        """
        Remove one file and its MediaStore row.

        Post: the gallery no longer lists it. A path MediaStore does not hold
              is not an error, so this is safe to call on a half-done run.
        """
        self.shell("content", "delete", "--uri", "content://media/external/file",
                   "--where", "\"_data='%s'\"" % storage_path)

    def date_added(self, storage_path: str) -> Optional[int]:
        """Post: MediaStore's date_added (epoch seconds) for the path, or None."""
        out = self.shell("content", "query", "--uri", "content://media/external/file",
                         "--projection", "date_added",
                         "--where", "\"_data='%s'\"" % storage_path)
        for line in out.splitlines():
            if "date_added=" in line:
                value = line.split("date_added=", 1)[1].split(",")[0].strip()
                return int(value) if value.isdigit() else None
        return None

    def utc_offset_seconds(self) -> int:
        """Post: the phone's current UTC offset, from `date +%z` (e.g. +0300)."""
        z = self.shell("date", "+%z").strip()
        if len(z) != 5 or z[0] not in "+-" or not z[1:].isdigit():
            raise DriverError("cannot read the phone's UTC offset: %r" % z)
        seconds = int(z[1:3]) * 3600 + int(z[3:5]) * 60
        return seconds if z[0] == "+" else -seconds

    def newest_gallery_item(self) -> Optional[str]:
        """
        The image or video MediaStore added last — the item a gallery picker
        such as Instagram's shows first under Recents.

        Post: its path as MediaStore stores it (/storage/emulated/0/...), or
              None when MediaStore holds no image or video.
        """
        out = self.shell("content", "query", "--uri", "content://media/external/file",
                         "--projection", "_data",
                         "--where", "'media_type=1 OR media_type=3'",
                         "--sort", "'date_added DESC, _id DESC'")
        for line in out.splitlines():
            if line.startswith("Row: 0 ") and "_data=" in line:
                return line.split("_data=", 1)[1].strip()
        return None

    def launch(self, package: str) -> None:
        self.shell("monkey", "-p", package, "-c",
                   "android.intent.category.LAUNCHER", "1")

    def foreground_package(self) -> Optional[str]:
        """
        Post: the package that owns the focused window, or None when the focus
              line is missing (the screen is off, or a transition is running).
        """
        out = self.shell("dumpsys", "window")
        for line in out.splitlines():
            if "mCurrentFocus" in line and "/" in line:
                token = line.rsplit(" ", 1)[-1]
                return token.split("/", 1)[0].strip("{}")
        return None

    def tap(self, x: int, y: int) -> None:
        self.shell("input", "tap", str(x), str(y))

    def keyevent(self, code: str) -> None:
        self.shell("input", "keyevent", code)

    def back(self) -> None:
        self.keyevent("KEYCODE_BACK")

    def set_ime(self, ime: str) -> None:
        self.shell("ime", "set", ime)

    def type_text(self, s: str) -> None:
        """Type through ADBKeyboard as base64 UTF-8, so Arabic and newlines survive."""
        b64 = base64.b64encode(s.encode("utf-8")).decode("ascii")
        self.shell("am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", b64)

    def ui_xml(self) -> str:
        """
        A fresh UiAutomator dump of the current screen.

        Post: the dump XML. Raises DriverError when the dump is empty, so a
        blank read never masquerades as "control not found".
        """
        self.shell("uiautomator", "dump", _UI_DUMP_PATH)
        xml = self.shell("cat", _UI_DUMP_PATH)
        if "<hierarchy" not in xml:
            raise DriverError("empty UiAutomator dump")
        return xml
