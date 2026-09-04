"""
services/itinerary/pipeline

The Bil Weekend itinerary pipeline, vendored into odysseus.

Templates and pricing in, a priced and validated itinerary document out. This
is the renderer `services/itinerary` drives; it was previously imported across a
filesystem path from a separate checkout, which meant odysseus could not run
without that checkout present.

Vendored from WebOperationsBilW on 2026-09-04 (ws-03 decision B1). The web GUI,
the desktop GUI, and their session password and sync PIN are deliberately not
part of this package — nothing here serves a UI.
"""
