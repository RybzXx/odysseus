"""
fedshi — Fedshi access, shared by content (media) and socialsrv (orders later).

Importing this package does NOT import Playwright. The engine lives in
fedshi.playwright_engine and is imported only when used, so the browser
dependency stays optional (spec 2.5.1).
"""
__version__ = "0.1.0"
