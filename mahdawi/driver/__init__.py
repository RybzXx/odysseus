"""
mahdawi.driver — post a packaged product to a phone app by driving its UI.

The driver resolves each control from a live UiAutomator dump (by resource-id,
content-desc, or visible text), never by fixed pixels, so a screen that scrolls
or shifts does not misfire. A per-app selector map (selectors/<app>.json) holds
the brittle strings, so a moved button is a data edit, not a code change.

Nothing here decides to post. A caller passes an already human-approved package;
dry_run stops before the final publish so the flow can be proven without a live
post (spec 0.2, 0.3).
"""
