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

    def launch(self, package: str) -> None:
        self.shell("monkey", "-p", package, "-c",
                   "android.intent.category.LAUNCHER", "1")

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
