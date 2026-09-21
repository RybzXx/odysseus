"""
fedshi.playwright_engine — the FedshiSource engine (spec OPEN-P2 = E1).

It drives a real Chromium so the product DOM renders exactly as the proven
manual extraction saw it. It reuses the saved login state headlessly and never
handles credentials: login() opens a headed window for the user to complete the
OTP, then saves the browser state.

This module imports Playwright. It is imported only when the engine is used, so
`import fedshi` still works with the browser dependency absent (spec 2.5.1).
"""
from __future__ import annotations

import json
from typing import List

from playwright.sync_api import sync_playwright

from mahdawi.fedshi import session
from mahdawi.fedshi.models import ListingEntry, ProductRecord
from mahdawi.fedshi.parse import build_record
from mahdawi.fedshi.source import ExtractionError, SessionExpired

# Reads the rendered product page. Same logic as the validated manual capture:
# media from currentSrc (decoding next/image wrappers to prod-media origins),
# plus the full body text for the label-anchored parser.
_EXTRACT_JS = r"""
() => {
  const origin = (u) => {
    try { const m = u.match(/\/_next\/image\?url=([^&]+)/); if (m) u = decodeURIComponent(m[1]); } catch (e) {}
    const m2 = u && u.match(/(https:\/\/prod-media\.fedshi\.com\/[^\s"')]+)/);
    return m2 ? m2[1] : u;
  };
  const imgs = [...new Set([...document.querySelectorAll('img')]
    .map(i => origin(i.currentSrc || i.src))
    .filter(u => u && u.includes('prod-media.fedshi.com/product_images')))];
  const vids = [...new Set([...document.querySelectorAll('video')]
    .map(v => v.currentSrc || v.src).filter(Boolean).map(origin))];
  return {
    url: location.href,
    title: (document.querySelector('h1') || {}).innerText || null,
    body_text: document.body.innerText,
    image_urls: imgs,
    video_urls: vids,
  };
}
"""

_LISTING_JS = r"""
() => {
  const seen = new Set(); const out = [];
  for (const a of document.querySelectorAll('a[href*="/products/"]')) {
    const href = a.getAttribute('href') || '';
    const sku = (href.split('/products/')[1] || '').split(/[/?#]/)[0];
    if (!sku || seen.has(sku)) continue;
    seen.add(sku);
    const txt = (a.innerText || '').replace(/\s+/g, ' ').trim();
    out.push({ sku, text: txt, is_bestseller: txt.includes('الأكثر مبيع') });
  }
  return out;
}
"""

# A product page that bounced to the login screen means the session is dead.
_LOGIN_MARKER = "/auth/login"


class PlaywrightFedshiSource:
    """A FedshiSource backed by headless Chromium reusing a saved login state."""

    def __init__(self, headless: bool = True, nav_timeout_ms: int = 45000):
        self.headless = headless
        self.nav_timeout_ms = nav_timeout_ms

    # -- login: the credential handoff ---------------------------------------
    def login(self, wait_seconds: int = 300) -> str:
        """
        Open a headed browser for the user to complete the OTP, then save state.

        Pre : called by the user, interactively.
        Post: the state file exists and holds an authenticated session.
        Invariant: this code enters no credentials. It waits for the user to
              leave the login page, then persists the browser's own state.
        """
        session.ensure_dir()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(session.LOGIN_URL, timeout=self.nav_timeout_ms)
            # Wait for the user to finish: the app leaves /auth/login on success.
            page.wait_for_url(lambda url: _LOGIN_MARKER not in url,
                              timeout=wait_seconds * 1000)
            context.storage_state(path=session.STATE_FILE)
            browser.close()
        return session.STATE_FILE

    # -- internal: a page on a restored session ------------------------------
    def _fronted(self, p):
        if not session.has_state():
            raise SessionExpired("no saved session; run login() first")
        browser = p.chromium.launch(headless=self.headless)
        context = browser.new_context(storage_state=session.STATE_FILE)
        page = context.new_page()
        page.set_default_timeout(self.nav_timeout_ms)
        return browser, page

    # -- fetch one product ---------------------------------------------------
    def fetch(self, sku: str) -> ProductRecord:
        with sync_playwright() as p:
            browser, page = self._fronted(p)
            try:
                page.goto(session.PRODUCT_URL % sku, timeout=self.nav_timeout_ms)
                page.wait_for_selector("h1", timeout=self.nav_timeout_ms)
                if _LOGIN_MARKER in page.url:
                    raise SessionExpired("product page bounced to login")
                raw = page.evaluate(_EXTRACT_JS)
            finally:
                browser.close()
        # F1: confirm the page stayed on the requested product. A bounce to
        # home or another product still renders an h1/title, so a title check
        # alone would extract the wrong item. The landed SKU must match.
        landed = session.product_sku_from_url(raw.get("url") or "")
        if landed != sku:
            raise ExtractionError(
                "fetch for %s landed on %r" % (sku, raw.get("url")))
        if not raw.get("title"):
            raise ExtractionError("no product title for %s" % sku)
        record = build_record(raw, sku)
        return record

    # -- list a collection ---------------------------------------------------
    def fetch_listing(self, collection: str) -> List[ListingEntry]:
        query = session.listing_query(collection)
        with sync_playwright() as p:
            browser, page = self._fronted(p)
            try:
                page.goto(session.LISTING_URL % query, timeout=self.nav_timeout_ms)
                page.wait_for_selector('a[href*="/products/"]', timeout=self.nav_timeout_ms)
                if _LOGIN_MARKER in page.url:
                    raise SessionExpired("listing page bounced to login")
                rows = page.evaluate(_LISTING_JS)
            finally:
                browser.close()
        return [ListingEntry(sku=r["sku"], title=r.get("text") or None,
                             is_bestseller=bool(r.get("is_bestseller"))) for r in rows]
