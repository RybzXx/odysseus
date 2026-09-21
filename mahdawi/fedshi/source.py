"""
fedshi.source — the FedshiSource seam.

One protocol, two methods. content/ (product media, P3) and socialsrv (order
status, later) both program against this, never against the Playwright engine.
So the engine dependency stays optional and the callers stay pure (spec 2.4.1,
2.5.1).

Importing this module must NOT import Playwright. The engine is imported lazily
by its own module, so `import fedshi` works with the browser dependency absent.
"""
from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from mahdawi.fedshi.models import ListingEntry, ProductRecord


class SessionExpired(RuntimeError):
    """The saved Fedshi session no longer authenticates. The user must re-login."""


class ExtractionError(RuntimeError):
    """The page loaded but the expected product content was not found."""


@runtime_checkable
class FedshiSource(Protocol):
    def fetch(self, sku: str) -> ProductRecord:
        """
        Pre : a valid session exists (the user logged in; state was saved).
        Post: a ProductRecord whose fields are read from the page or None —
              never invented.
        Raises: SessionExpired, ExtractionError.
        """

    def fetch_listing(self, collection: str) -> List[ListingEntry]:
        """
        List SKUs on a collection page for selection.

        Pre : collection is "new", "bestseller", or a "collection-id=<n>" string.
        Post: entries in page order; [] when the listing is empty.
        Raises: SessionExpired.
        """
