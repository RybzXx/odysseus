"""
mahdawi.driver.tiktok — post one packaged product to TikTok by driving the app.

TikTok gets the image through an Android share intent, not through its own
gallery picker. That choice is not a shortcut: TikTok opens on its video feed,
and a playing feed never reaches the idle state a UiAutomator dump needs, so
the feed's controls cannot be resolved at all. The intent skips the feed and
lands on "Share on TikTok", which is a static screen.

The flow after that is TikTok's own: Photo -> Next -> the post screen, where
the caption goes into the description field and Post publishes.

Contract:
  Pre : package_dir holds a caption file and at least one image; the phone is
        awake, TikTok is installed and logged in.
  Post: dry_run -> {"status": "dry_run_ready"} with Post resolved, nothing posted.
        live    -> {"status": "posted"} after the Post tap.
  Invariant: the home keyboard is restored even when a step raises.
"""
from __future__ import annotations

import os

from mahdawi.driver.adb import ADBKEYBOARD_IME
from mahdawi.driver.app_flow import AppDriver, first_image, read_package
from mahdawi.driver.errors import DriverError

CHANNEL = "tiktok"


class TikTokDriver(AppDriver):
    def __init__(self, adb=None, selectors=None, home_ime=None, settle: float = 3.0):
        super().__init__(CHANNEL, adb=adb, selectors=selectors, home_ime=home_ime,
                         settle=settle)

    def _share_image(self, media_id: int) -> None:
        """
        Pre : media_id is the pushed image's MediaStore id.
        Post: TikTok owns the screen with its share sheet for that image.
        Raises: DriverError when TikTok does not come to the front.
        """
        package = self.sel["app_package"]
        self.adb.share_image(media_id, package)
        self._await_front(package)
        self.steps.append("shared media id %d to %s" % (media_id, package))

    def _require_empty_description(self, retries: int = 20) -> None:
        """
        Wait for a post screen whose description is still empty.

        The description selector matches TikTok's placeholder, and the
        placeholder disappears once the field holds text. TikTok also resumes
        an unfinished post: on 2026-09-22 a run met the previous run's caption
        and could not resolve the field at all. Typing there would append one
        caption to another, so an unfinished post stops the run instead.

        Post: the description field is on screen and empty.
        Raises: DriverError on an unfinished post, or when the post screen
              never arrives.
        """
        if self._resolve("description_field", retries=retries):
            return
        if self._resolve("post_button", retries=1):
            raise DriverError("TikTok is holding an unfinished post. Open TikTok, "
                              "post or discard it, then run again")
        raise DriverError("the TikTok post screen did not open")

    def _abandon_post(self, steps_back: int = 3) -> None:
        """
        Leave the post flow this run opened and discard its draft.

        A failed run that already typed a caption leaves an unfinished post,
        and TikTok resumes it: the next run then stops on that leftover
        (live, 2026-09-22). Never raises — the real error must survive.

        Pre : this run typed into the post screen.
        Post: no draft of this run's making is left open.
        """
        try:
            for _ in range(steps_back):
                if self._tap("discard_option", required=False, retries=2):
                    self.steps.append("discarded the unfinished post")
                    return
                if not self._tap("leave_screen", required=False, retries=1):
                    return
                self._wait()
            self._tap("discard_option", required=False, retries=2)
        except DriverError:
            self.steps.append("could not leave the post flow")

    def _reach_post_button(self, attempts: int = 3):
        """
        Close the hashtag suggestion panel and return the Post button.

        A caption with hashtags opens that panel, and it hides Post and every
        control under the caption. Back does not close it: back leaves the post
        screen. A tap on the empty strip beside the cover thumbnails closes it
        and changes nothing else, but one tap is not always enough — the panel
        comes back while the field still holds the focus (live, 2026-09-22).

        While the caption field holds the focus, TikTok carries the bottom bar
        in a window of its own, and a UiAutomator dump of the focused window
        holds Preview and More options but no Post at all (live, 2026-09-22).
        Each attempt closes the keyboard, taps the empty strip, and scrolls up.
        When Post still does not resolve, its fixed position serves instead —
        but only once another control proves this IS the post screen, so the
        driver never taps a position on an unknown screen.

        Post: (x, y) of the Post button.
        Raises: DriverError when the post screen itself cannot be confirmed.
        """
        moves = (("closed the keyboard", self.adb.hide_keyboard),
                 ("closed the hashtag suggestions", lambda: self._tap("blank_area")),
                 ("scrolled the post screen up",
                  lambda: self.adb.swipe(720, 2000, 720, 1200)))
        for _ in range(attempts):
            node = self._resolve("post_button", retries=3)
            if node:
                return node.center()
            for label, move in moves:
                move()
                self.steps.append(label)
                self._wait()
                node = self._resolve("post_button", retries=2)
                if node:
                    return node.center()

        if not self._resolve("post_screen", retries=3):
            raise DriverError("post button not reachable, and this is not the post screen")
        width, height = self._screen_size()
        fx, fy = self.sel["post_button"]["fallback_xy"]
        self.steps.append("post button taken from its fixed position")
        return int(width * fx), int(height * fy)

    # -- the flow ------------------------------------------------------------
    def post(self, package_dir: str, dry_run: bool = True) -> dict:
        caption, media = read_package(package_dir, CHANNEL)
        target = first_image(media)       # one photo per post; carousel later
        sku = os.path.basename(os.path.normpath(package_dir))
        remote = self.remote_name(sku, target)
        try:
            media_id = self._push_to_gallery(target, remote)
        except DriverError:
            self._drop_from_gallery(remote)
            raise

        self.adb.set_ime(ADBKEYBOARD_IME)
        typed = False                     # a typed caption becomes a draft to clear
        try:
            self._share_image(media_id)                # share sheet, image attached
            self._wait()
            # A cold TikTok reaches the front on its feed and builds the share
            # sheet seconds later, so each screen gets a long wait (live).
            self._tap("share_as_photo", retries=20); self._wait()   # sheet -> editor
            self._tap("next", retries=20); self._wait()             # editor -> post screen
            # The post screen builds slowly after Next: about 8 s live.
            self._require_empty_description()
            self._type_into("description_field", caption, retries=1)
            typed = True
            post_x, post_y = self._reach_post_button()

            if dry_run:
                self.steps.append("dry_run: Post reachable, not tapped")
                # The draft must go: TikTok resumes it and the next run stops
                # on it, and it is not the owner's post to keep.
                self._abandon_post()
                self._drop_from_gallery(remote)
                return {"status": "dry_run_ready", "sku": sku, "steps": self.steps}

            self.adb.tap(post_x, post_y)
            self.steps.append("tapped Post")
            self._wait()
            return {"status": "posted", "sku": sku, "steps": self.steps}
        except DriverError:
            if typed:
                self._abandon_post()
            self._drop_from_gallery(remote)
            raise
        finally:
            self.adb.set_ime(self.home_ime)
