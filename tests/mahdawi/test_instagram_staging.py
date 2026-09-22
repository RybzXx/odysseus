"""
tests/mahdawi/test_instagram_staging.py

The Instagram driver's media staging, against a fake phone. The New post screen
auto-selects the newest gallery item, so the driver must not open the app until
the pushed image is that item (bug 7, 2026-09-22), and it must read the package
in the pipeline's order with the Instagram caption.
"""
import json

import pytest

from mahdawi.driver import instagram
from mahdawi.driver.errors import DriverError
from mahdawi.driver.instagram import InstagramDriver, _read_package, first_image


class FakePhone:
    """Records calls; MediaStore reports `newest` once `index_after` scans have run."""

    def __init__(self, index_after=1, stale="/storage/emulated/0/Pictures/mahdawi-logo.png"):
        self.calls, self.scans, self.index_after, self.stale = [], 0, index_after, stale
        self.pushed = None

    def shell(self, *args):
        self.calls.append(("shell",) + args)
        return ""

    def push(self, local, remote):
        self.calls.append(("push", remote))
        self.pushed = remote

    def touch(self, remote):
        self.calls.append(("touch", remote))

    def media_scan(self, remote):
        self.scans += 1

    def delete_media(self, storage_path):
        self.calls.append(("delete", storage_path))

    def newest_gallery_item(self):
        if self.index_after is not None and self.scans >= self.index_after:
            return self.pushed.replace("/sdcard/", "/storage/emulated/0/")
        return self.stale


@pytest.fixture()
def fast(monkeypatch):
    monkeypatch.setattr(instagram.time, "sleep", lambda s: None)


def _driver(phone):
    return InstagramDriver(adb=phone, selectors={"app_package": "x"})


def test_staging_waits_until_the_image_is_newest(fast, tmp_path):
    phone = FakePhone(index_after=3)
    d = _driver(phone)
    d._stage_in_gallery(str(tmp_path / "a.png"), "/sdcard/Pictures/mahdawi/S_1_a.png")
    assert phone.scans == 3
    assert ("touch", "/sdcard/Pictures/mahdawi/S_1_a.png") in phone.calls
    assert "newest in gallery" in d.steps[-1]


def test_staging_fails_closed_when_another_item_stays_newest(fast, tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "_SCAN_WAIT_SECONDS", 0.05)
    with pytest.raises(DriverError, match="not the newest gallery item"):
        _driver(FakePhone(index_after=None))._stage_in_gallery(
            str(tmp_path / "a.png"), "/sdcard/Pictures/mahdawi/S_1_a.png")


def test_post_never_opens_the_app_when_staging_fails(fast, tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "_SCAN_WAIT_SECONDS", 0.05)
    (tmp_path / "caption.txt").write_text("c", encoding="utf-8")
    (tmp_path / "a.png").write_bytes(b"i")
    phone = FakePhone(index_after=None)
    with pytest.raises(DriverError):
        _driver(phone).post(str(tmp_path), dry_run=True)
    assert not any(c[:2] == ("shell", "monkey") for c in phone.calls)


def test_each_run_pushes_a_fresh_name(fast, tmp_path, monkeypatch):
    # A re-pushed existing name keeps its old date_added and is not newest.
    (tmp_path / "caption.txt").write_text("c", encoding="utf-8")
    (tmp_path / "a.png").write_bytes(b"i")
    names = []
    for t in (1000, 2000):
        monkeypatch.setattr(instagram.time, "time", lambda t=t: t)
        phone = FakePhone(index_after=None)
        monkeypatch.setattr(instagram, "_SCAN_WAIT_SECONDS", 0)
        with pytest.raises(DriverError):
            _driver(phone).post(str(tmp_path), dry_run=True)
        names.append(phone.pushed)
    assert names[0] != names[1]


def test_package_order_comes_from_meta_and_instagram_caption_wins(tmp_path):
    (tmp_path / "caption.txt").write_text("shared", encoding="utf-8")
    (tmp_path / "caption_instagram.txt").write_text("insta", encoding="utf-8")
    for n in ("v.mp4", "b.png", "a.png"):
        (tmp_path / n).write_bytes(b"x")
    (tmp_path / "meta.json").write_text(json.dumps({"media": ["v.mp4", "b.png", "a.png"]}))
    caption, media = _read_package(str(tmp_path))
    assert caption == "insta"
    assert [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in media] == ["v.mp4", "b.png", "a.png"]
    assert first_image(media).endswith("b.png")


def test_a_package_of_only_video_is_refused(tmp_path):
    (tmp_path / "caption.txt").write_text("c", encoding="utf-8")
    (tmp_path / "v.mp4").write_bytes(b"x")
    _c, media = _read_package(str(tmp_path))
    with pytest.raises(DriverError, match="no image"):
        first_image(media)


def test_meta_listing_a_missing_file_skips_it(tmp_path):
    (tmp_path / "caption.txt").write_text("c", encoding="utf-8")
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "meta.json").write_text(json.dumps({"media": ["gone.png", "a.png"]}))
    _c, media = _read_package(str(tmp_path))
    assert len(media) == 1 and media[0].endswith("a.png")


# -- the selection check on the New post screen --------------------------------------
def _screen(desc, partial=False):
    nodes = ['<node resource-id="" text="" content-desc="%s" bounds="[0,0][10,10]" />' % desc]
    if partial:
        nodes.append('<node resource-id="com.instagram.android:id/root_partial_permission_view" '
                     'text="" content-desc="" bounds="[0,0][10,10]" />')
    return "<hierarchy>%s</hierarchy>" % "".join(nodes)


class SelectPhone(FakePhone):
    def __init__(self, xml, added=1789918539, offset=3 * 3600):
        super().__init__()
        self.xml, self.added, self.offset = xml, added, offset

    def ui_xml(self):
        return self.xml

    def date_added(self, path):
        return self.added

    def utc_offset_seconds(self):
        return self.offset


def _check(phone):
    InstagramDriver(adb=phone)._check_selection("/sdcard/Pictures/mahdawi/x.png")


def test_selection_matching_the_pushed_minute_passes():
    # 1789918539 = 2026-09-20 15:35:39 UTC = 18:35 at +03:00.
    _check(SelectPhone(_screen("Selected Photo thumbnail created on 20 September 2026 18:35")))


@pytest.mark.parametrize("desc", [
    "Selected Photo thumbnail created on 20 September 2026 18:36",   # one minute off
    "Selected Photo thumbnail created on 21 September 2026 18:35",   # one day off
    "Photo thumbnail created on 20 September 2026 18:35",            # nothing selected
    "Selected Photo thumbnail created on 20 Septembre 2026 18:35",   # unknown month
])
def test_any_other_selection_fails_closed(desc):
    with pytest.raises(DriverError):
        _check(SelectPhone(_screen(desc)))


def test_partial_photo_access_fails_closed_with_the_fix():
    xml = _screen("Selected Photo thumbnail created on 20 September 2026 18:35", partial=True)
    with pytest.raises(DriverError, match="Allow all"):
        _check(SelectPhone(xml))


def test_file_missing_from_mediastore_fails_closed():
    phone = SelectPhone(_screen("Selected Photo thumbnail created on 20 September 2026 18:35"),
                        added=None)
    with pytest.raises(DriverError, match="cannot confirm"):
        _check(phone)


@pytest.mark.parametrize("epoch,offset,expected", [
    (1789918539, 3 * 3600, (2026, 9, 20, 18, 35)),
    (1789918539, 0, (2026, 9, 20, 15, 35)),
    (1789937999, 3 * 3600, (2026, 9, 20, 23, 59)),     # one second before local midnight
    (1789938000, 3 * 3600, (2026, 9, 21, 0, 0)),      # local midnight
    (1789918539, -5 * 3600, (2026, 9, 20, 10, 35)),
])
def test_local_minute(epoch, offset, expected):
    assert instagram.local_minute(epoch, offset) == expected


# -- where the app resumes -------------------------------------------------------------
class ResumePhone(FakePhone):
    """
    A screen state machine. "profile": the fixed create tap opens the Create
    sheet (observed 2026-09-22 when Instagram resumed on the Profile tab).
    "sheet": tapping its Post row opens the select screen. "select": Next shows.
    """
    SCREENS = {
        "profile": '<node resource-id="" text="" content-desc="Profile" bounds="[0,0][10,10]" />',
        "sheet": '<node resource-id="" text="Post" content-desc="" bounds="[0,1100][900,1200]" />'
                 '<node resource-id="" text="Reel" content-desc="" bounds="[0,850][900,950]" />',
        "select": '<node resource-id="" text="Next" content-desc="Next" bounds="[1200,200][1400,260]" />',
    }

    def __init__(self, start="profile"):
        super().__init__()
        self.state = start

    def ui_xml(self):
        return "<hierarchy>%s</hierarchy>" % self.SCREENS[self.state]

    def tap(self, x, y):
        if self.state == "profile":
            self.state = "sheet"
        elif self.state == "sheet" and 1100 <= y <= 1200:
            self.state = "select"

    def shell(self, *args):
        if args[:2] == ("wm", "size"):
            return "Physical size: 1440x3120"
        return super().shell(*args)

    def launch(self, package):
        pass

    def set_ime(self, ime):
        pass


def test_open_create_from_the_profile_tab_reaches_the_select_screen(fast):
    # BUG-9: Instagram resumed on Profile, the fixed "+" tap opened the Create
    # sheet, and the driver never tapped Post.
    phone = ResumePhone(start="profile")
    InstagramDriver(adb=phone, settle=0)._open_create()
    assert phone.state == "select"


def test_open_create_from_the_home_tab_reaches_the_select_screen(fast):
    phone = ResumePhone(start="profile")
    phone.SCREENS = dict(ResumePhone.SCREENS)
    InstagramDriver(adb=phone, settle=0)._open_create()
    assert phone.state == "select"


def test_open_create_does_nothing_when_the_select_screen_is_already_open(fast):
    phone = ResumePhone(start="select")
    InstagramDriver(adb=phone, settle=0)._open_create()
    assert phone.state == "select"


def test_open_create_still_gives_up_when_no_screen_answers(fast):
    class Stuck(ResumePhone):
        def tap(self, x, y):
            pass                      # every tap is swallowed
    with pytest.raises(DriverError, match="New post did not open"):
        InstagramDriver(adb=Stuck(start="profile"), settle=0)._open_create()


def test_a_failed_run_removes_the_image_it_pushed(fast, tmp_path, monkeypatch):
    monkeypatch.setattr(instagram, "_SCAN_WAIT_SECONDS", 0.05)
    (tmp_path / "caption.txt").write_text("c", encoding="utf-8")
    (tmp_path / "a.png").write_bytes(b"i")
    phone = FakePhone(index_after=None)
    with pytest.raises(DriverError):
        _driver(phone).post(str(tmp_path), dry_run=True)
    pushed = phone.pushed.replace("/sdcard/", "/storage/emulated/0/")
    assert ("delete", pushed) in phone.calls


def test_a_run_that_fails_after_staging_also_removes_the_image(fast, tmp_path):
    (tmp_path / "caption.txt").write_text("c", encoding="utf-8")
    (tmp_path / "a.png").write_bytes(b"i")

    class NoScreens(FakePhone):
        def ui_xml(self):
            return "<hierarchy></hierarchy>"

        def shell(self, *args):
            if args[:2] == ("wm", "size"):
                return "Physical size: 1440x3120"
            return super().shell(*args)

        def launch(self, package):
            pass

        def set_ime(self, ime):
            pass

        def tap(self, x, y):
            pass

        def foreground_package(self):
            return "com.instagram.android"

    phone = NoScreens(index_after=1)
    with pytest.raises(DriverError, match="New post did not open"):
        InstagramDriver(adb=phone, settle=0).post(str(tmp_path), dry_run=True)
    assert any(c[0] == "delete" for c in phone.calls)


# -- the app must own the screen before any tap ----------------------------------------
class LaunchPhone(FakePhone):
    """Comes to the front after `ready_after` polls; never, when that is None."""

    def __init__(self, ready_after=1, other="com.termux"):
        super().__init__()
        self.polls, self.ready_after, self.other = 0, ready_after, other

    def launch(self, package):
        self.calls.append(("launch", package))

    def foreground_package(self):
        self.polls += 1
        if self.ready_after is not None and self.polls > self.ready_after:
            return "com.instagram.android"
        return self.other


def test_launch_waits_until_the_app_is_in_front(fast):
    phone = LaunchPhone(ready_after=2)
    InstagramDriver(adb=phone, settle=0)._launch_and_wait()
    assert phone.polls == 3
    assert ("launch", "com.instagram.android") in phone.calls


def test_launch_fails_closed_when_another_app_keeps_the_screen(fast, monkeypatch):
    # BUG-11: the driver tapped into Termux while Instagram was still starting.
    monkeypatch.setattr(instagram, "_LAUNCH_WAIT_SECONDS", 0.05)
    with pytest.raises(DriverError, match="did not come to the front"):
        InstagramDriver(adb=LaunchPhone(ready_after=None), settle=0)._launch_and_wait()


def test_foreground_package_parses_the_focus_line():
    from mahdawi.driver.adb import Adb

    class Shell(Adb):
        def __init__(self, out):
            super().__init__(bin="adb")
            self.out = out

        def shell(self, *args):
            return self.out

    line = "  mCurrentFocus=Window{36abd5b u0 com.instagram.android/com.instagram.android.activity.MainTabActivity}"
    assert Shell(line).foreground_package() == "com.instagram.android"
    assert Shell("  mCurrentFocus=null").foreground_package() is None
    assert Shell("").foreground_package() is None
