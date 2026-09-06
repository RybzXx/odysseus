"""
services/curated — the request side of the itinerary desk.

Vendored from OperationsAutomationSrv/curated at 3944ecc, with one change: the
pipeline coupling now resolves against this repository's own vendored pipeline
rather than BILWEEKEND_REPO_ROOT, which this repository removed on purpose.

`runner` and `sheets_client` are deliberately not vendored. They take a lock and
write six cells back to the operations sheet, and a write to that sheet must not
arrive as a side effect of an import here.
"""
