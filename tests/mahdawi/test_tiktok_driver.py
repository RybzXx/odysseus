"""
tests/mahdawi/test_tiktok_driver.py

The TikTok driver against a fake phone. TikTok takes the image through a share
intent, because its video feed never reaches the idle state a UiAutomator dump
needs. The flow then is Photo -> Next -> post screen, and Post is tapped only
on a live run.
"""
import json

import pytest

from mahdawi.driver import app_flow
from mahdawi.driver.errors import DriverError
from mahdawi.driver.tiktok import TikTokDriver

PACKAGE = "com.zhiliaoapp.musically"
SCREENS = {
    "share_sheet": '<node resource-id="" text="Photo" content-desc="" bounds="[100,2500][700,2700]" />',
    "editor": '<node resource-id="" text="Next" content-desc="" bounds="[900,2700][1400,2900]" />',
    # Typing hashtags opens the suggestion panel, which hides Post until Back.
    "post_suggestions": '<node resource-id="" text="Writing a long description can help" content-desc="" bounds="[60,889][1380,1417]" />'
                        '<node resource-id="" text="Add a catchy title" content-desc="" bounds="[60,738][1380,812]" />'
                        '<node resource-id="" text="" content-desc="More options" bounds="[0,1787][1440,1966]" />',
    "post": '<node resource-id="" text="Writing a long description can help" content-desc="" bounds="[60,889][1380,1417]" />'
            '<node resource-id="" text="Post" content-desc="" bounds="[735,2715][1395,2895]" />',
    "discard_prompt": '<node resource-id="" text="Discard" content-desc="" bounds="[203,454][712,529]" />'
                      '<node resource-id="" text="Save draft" content-desc="" bounds="[203,635][712,710]" />',
    "gone": "",
}


class TikTokPhone:
    """Share intent -> share sheet; each tap moves one screen on."""

    def __init__(self, media_indexed=True, front=PACKAGE):
        self.calls, self.state, self.front = [], "none", front
        self.media_indexed, self.typed, self.pushed = media_indexed, None, None

    # -- app_flow needs these ------------------------------------------------
    def shell(self, *args):
        if args[:2] == ("wm", "size"):
            return "Physical size: 1440x3120"
        self.calls.append(("shell",) + args)
        return ""

    def push(self, local, remote):
        self.pushed = remote

    def touch(self, remote):
        pass

    def media_scan(self, remote):
        pass

    def media_id(self, storage_path):
        return 5652 if self.media_indexed else None

    def delete_media(self, storage_path):
        self.calls.append(("delete", storage_path))

    def set_ime(self, ime):
        self.calls.append(("ime", ime))

    def foreground_package(self):
        return self.front

    def share_image(self, media_id, package):
        self.calls.append(("share", media_id, package))
        self.state = "share_sheet"

    def ui_xml(self):
        return "<hierarchy>%s</hierarchy>" % SCREENS.get(self.state, "")

    def tap(self, x, y):
        self.calls.append(("tap", x, y))
        if self.state == "share_sheet":
            self.state = "editor"
        elif self.state == "editor":
            self.state = "post_suggestions"
        elif self.state == "post_suggestions" and y < 900:
            self.state = "post"        # focus left the description; the panel closes
        elif self.state == "discard_prompt" and 454 <= y <= 529:
            self.state = "discarded"
        elif x < 200 and y < 300:
            self._leave()              # the top-left arrow

    def type_text(self, text):
        self.typed = text

    def hide_keyboard(self):
        self.calls.append(("hide_keyboard",))
        if self.state == "post_suggestions":
            self.state = "post"       # the bottom bar returns with the keyboard gone

    def swipe(self, x1, y1, x2, y2, ms=300):
        self.calls.append(("swipe", y1, y2))

    def back(self):
        self.calls.append(("back",))
        self.state = "gone"           # back leaves the post screen, as it does live

    def _leave(self):
        """The top-left arrow walks back, and the prompt offers Discard."""
        self.state = "discard_prompt" if self.state in ("post", "post_suggestions") else "gone"


@pytest.fixture()
def fast(monkeypatch):
    monkeypatch.setattr(app_flow.time, "sleep", lambda s: None)


def _package(tmp_path, tiktok_caption="تيك توك", shared="مشترك", image="a.png"):
    (tmp_path / "caption.txt").write_text(shared, encoding="utf-8")
    if tiktok_caption is not None:
        (tmp_path / "caption_tiktok.txt").write_text(tiktok_caption, encoding="utf-8")
    (tmp_path / image).write_bytes(b"i")
    (tmp_path / "meta.json").write_text(json.dumps({"media": [image]}))
    return str(tmp_path)


def test_dry_run_reaches_post_and_never_taps_it(fast, tmp_path):
    phone = TikTokPhone()
    d = TikTokDriver(adb=phone, settle=0)
    out = d.post(_package(tmp_path), dry_run=True)
    assert out["status"] == "dry_run_ready"
    assert ("share", 5652, PACKAGE) in phone.calls
    assert phone.typed == "تيك توك"            # the TikTok caption, not the shared one
    assert "dry_run: Post reachable, not tapped" in d.steps
    assert phone.state == "discarded"          # the dry run clears its own draft


def test_a_live_run_taps_post_once(fast, tmp_path):
    phone = TikTokPhone()
    d = TikTokDriver(adb=phone, settle=0)
    out = d.post(_package(tmp_path), dry_run=False)
    # the Post button's centre, from its bounds in SCREENS["post"]
    taps_on_post = [c for c in phone.calls if c[0] == "tap" and c[1:] == (1065, 2805)]
    assert out["status"] == "posted" and len(taps_on_post) == 1
    assert d.steps[-1] == "tapped Post"


def test_the_shared_caption_is_used_when_the_channel_file_is_missing(fast, tmp_path):
    phone = TikTokPhone()
    TikTokDriver(adb=phone, settle=0).post(_package(tmp_path, tiktok_caption=None),
                                           dry_run=True)
    assert phone.typed == "مشترك"


def test_a_video_only_package_is_refused(fast, tmp_path):
    phone = TikTokPhone()
    with pytest.raises(DriverError, match="no image"):
        TikTokDriver(adb=phone, settle=0).post(_package(tmp_path, image="v.mp4"),
                                               dry_run=True)
    assert phone.pushed is None               # nothing reached the phone


def test_an_unindexed_image_fails_closed_and_cleans_up(fast, tmp_path, monkeypatch):
    monkeypatch.setattr(app_flow, "SCAN_WAIT_SECONDS", 0.05)
    phone = TikTokPhone(media_indexed=False)
    with pytest.raises(DriverError, match="did not index"):
        TikTokDriver(adb=phone, settle=0).post(_package(tmp_path), dry_run=True)
    assert any(c[0] == "delete" for c in phone.calls)
    assert not any(c[0] == "share" for c in phone.calls)


def test_tiktok_not_coming_to_the_front_fails_closed(fast, tmp_path, monkeypatch):
    monkeypatch.setattr(app_flow, "LAUNCH_WAIT_SECONDS", 0.05)
    phone = TikTokPhone(front="com.termux")
    with pytest.raises(DriverError, match="did not come to the front"):
        TikTokDriver(adb=phone, settle=0).post(_package(tmp_path), dry_run=True)
    assert any(c[0] == "delete" for c in phone.calls)


def test_the_home_keyboard_returns_after_a_failure(fast, tmp_path, monkeypatch):
    monkeypatch.setattr(app_flow, "LAUNCH_WAIT_SECONDS", 0.05)
    phone = TikTokPhone(front="com.termux")
    with pytest.raises(DriverError):
        TikTokDriver(adb=phone, settle=0).post(_package(tmp_path), dry_run=True)
    ime_calls = [c[1] for c in phone.calls if c[0] == "ime"]
    assert ime_calls[-1] == app_flow.HOME_IME_DEFAULT


def test_the_suggestion_panel_is_closed_before_post_is_read(fast, tmp_path):
    # Live on 2026-09-22 the hashtag panel covered Post and the run stopped;
    # back left the screen, so the driver moves the focus instead.
    phone = TikTokPhone()
    d = TikTokDriver(adb=phone, settle=0)
    d.post(_package(tmp_path), dry_run=True)
    assert ("back",) not in phone.calls          # back leaves the screen live
    assert phone.state == "discarded" and "typed" not in d.steps[-1]


class NoDismissPhone(TikTokPhone):
    """Nothing reveals the bottom bar: no dismissal, no scroll."""

    def tap(self, x, y):
        self.calls.append(("tap", x, y))
        if self.state == "share_sheet":
            self.state = "editor"
        elif self.state == "editor":
            self.state = "post_suggestions"

    def hide_keyboard(self):
        self.calls.append(("hide_keyboard",))

    def swipe(self, x1, y1, x2, y2, ms=300):
        self.calls.append(("swipe", y1, y2))


def test_a_confirmed_post_screen_uses_the_fixed_post_position(fast, tmp_path):
    # Live, Post sits in a window a dump does not reach. The fallback fires
    # only once another control proves this is the post screen.
    phone = NoDismissPhone()
    d = TikTokDriver(adb=phone, settle=0)
    d.post(_package(tmp_path), dry_run=False)
    assert "post button taken from its fixed position" in d.steps
    assert ("tap", 1065, 2804) in phone.calls


class ResumedPostPhone(TikTokPhone):
    """TikTok resumed an unfinished post: the caption field holds text already,
    so its placeholder is gone, and Post is on screen."""

    def ui_xml(self):
        if self.state in ("post_suggestions", "post"):
            return ('<hierarchy><node resource-id="" text="Post" content-desc="" '
                    'bounds="[735,2715][1395,2895]" /></hierarchy>')
        return super().ui_xml()


def test_an_unfinished_post_stops_the_run(fast, tmp_path):
    phone = ResumedPostPhone()
    with pytest.raises(DriverError, match="unfinished post"):
        TikTokDriver(adb=phone, settle=0).post(_package(tmp_path), dry_run=True)
    assert phone.typed is None                      # nothing was appended
    assert any(c[0] == "delete" for c in phone.calls)


class NoPostScreenPhone(TikTokPhone):
    def ui_xml(self):
        if self.state in ("post_suggestions", "post"):
            return "<hierarchy></hierarchy>"        # the screen never builds
        return super().ui_xml()


def test_a_post_screen_that_never_opens_stops_the_run(fast, tmp_path):
    phone = NoPostScreenPhone()
    with pytest.raises(DriverError, match="post screen did not open"):
        TikTokDriver(adb=phone, settle=0).post(_package(tmp_path), dry_run=True)
    assert phone.typed is None


def test_a_dry_run_leaves_no_draft_behind(fast, tmp_path):
    # A kept draft blocks the next run: TikTok resumes it.
    phone = TikTokPhone()
    d = TikTokDriver(adb=phone, settle=0)
    d.post(_package(tmp_path), dry_run=True)
    assert phone.state == "discarded"
    assert "discarded the unfinished post" in d.steps
    assert any(c[0] == "delete" for c in phone.calls)


def test_a_live_post_keeps_its_screen(fast, tmp_path):
    phone = TikTokPhone()
    d = TikTokDriver(adb=phone, settle=0)
    d.post(_package(tmp_path), dry_run=False)
    assert phone.state != "discarded"          # the post is on its way
    assert "discarded the unfinished post" not in d.steps


def test_a_failure_before_typing_leaves_the_app_alone(fast, tmp_path, monkeypatch):
    monkeypatch.setattr(app_flow, "LAUNCH_WAIT_SECONDS", 0.05)
    phone = TikTokPhone(front="com.termux")
    with pytest.raises(DriverError):
        TikTokDriver(adb=phone, settle=0).post(_package(tmp_path), dry_run=True)
    assert not any(c[0] == "tap" for c in phone.calls)   # no blind back taps


def test_the_keyboard_is_closed_before_post_is_sought(fast, tmp_path):
    # While the caption field holds the focus, TikTok keeps the bottom bar —
    # and Post with it — out of the layout entirely (live, 2026-09-22).
    phone = TikTokPhone()
    d = TikTokDriver(adb=phone, settle=0)
    d.post(_package(tmp_path), dry_run=True)
    assert ("hide_keyboard",) in phone.calls
    assert "closed the keyboard" in d.steps


class KeyboardStuckPhone(TikTokPhone):
    def hide_keyboard(self):
        self.calls.append(("hide_keyboard",))      # the bar stays hidden

    def tap(self, x, y):
        self.calls.append(("tap", x, y))
        if self.state == "share_sheet":
            self.state = "editor"
        elif self.state == "editor":
            self.state = "post_suggestions"

    def swipe(self, x1, y1, x2, y2, ms=300):
        self.calls.append(("swipe", y1, y2))
        if self.state == "post_suggestions":
            self.state = "post"                    # scrolling reveals the bar


def test_a_scroll_recovers_a_post_button_below_the_fold(fast, tmp_path):
    phone = KeyboardStuckPhone()
    d = TikTokDriver(adb=phone, settle=0)
    assert d.post(_package(tmp_path), dry_run=True)["status"] == "dry_run_ready"
    assert any(c[0] == "swipe" for c in phone.calls)


class UnknownScreenPhone(NoDismissPhone):
    """No control on screen says which screen this is."""

    def ui_xml(self):
        if self.state == "post_suggestions":
            return ('<hierarchy><node resource-id="" text="Writing a long description can help"'
                    ' content-desc="" bounds="[60,889][1380,1417]" /></hierarchy>')
        return super().ui_xml()


def test_an_unconfirmed_screen_never_taps_a_fixed_position(fast, tmp_path):
    phone = UnknownScreenPhone()
    with pytest.raises(DriverError, match="not the post screen"):
        TikTokDriver(adb=phone, settle=0).post(_package(tmp_path), dry_run=False)
    assert ("tap", 1065, 2804) not in phone.calls      # the Post position
