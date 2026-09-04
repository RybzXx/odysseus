"""
BilWeekend — Google API Clients
Process-wide cached clients, built once and shared.

Constructing a googleapiclient resource is expensive in a way that is easy to
miss: the library generates a docstring for every method by pretty-printing the
API's discovery schemas. Measured on this project:

    svc.spreadsheets()                57 MB
    svc.spreadsheets().values()       22 MB
    docs_svc.documents()              37 MB
    the actual HTTP call            0.21 MB

Code that writes `service.spreadsheets().values().get(...)` inside a loop or a
request handler therefore pays tens of megabytes per call for nothing. On a
512 MB instance that is the difference between running and being killed.

Resources are shared across threads; the http transport is not, because
httplib2.Http is not thread-safe. Each thread gets its own, which also keeps its
connection alive between calls.
"""
from __future__ import annotations

import os
import threading

import google_auth_httplib2
import httplib2
from google.oauth2 import service_account
from googleapiclient.discovery import build

from services.itinerary.pipeline import config

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

# Reentrant: sheet_values() is built by calling spreadsheets(), so the factory
# for one entry can ask for another while the lock is already held.
_build_lock = threading.RLock()
_thread_local = threading.local()
_cache: dict = {}


def credentials():
    """
    The service-account credentials, built once.

    Pre:  config.CREDENTIALS_FILE exists.
    Post: returns the same object on every call; raises FileNotFoundError when
          the credentials file is absent.
    """
    return _cached("credentials", _load_credentials)


def _load_credentials():
    if not os.path.exists(config.CREDENTIALS_FILE):
        raise FileNotFoundError(f"Credentials file not found: {config.CREDENTIALS_FILE}")
    return service_account.Credentials.from_service_account_file(
        config.CREDENTIALS_FILE, scopes=SCOPES,
    )


def spreadsheets():
    """The Sheets `spreadsheets` resource — for metadata reads and batchUpdate."""
    return _cached("spreadsheets", lambda: _service("sheets", "v4").spreadsheets())


def sheet_values():
    """The Sheets `spreadsheets.values` resource — for get, batchGet, update, clear."""
    return _cached("sheet_values", lambda: spreadsheets().values())


def documents():
    """The Docs `documents` resource."""
    return _cached("documents", lambda: _service("docs", "v1").documents())


def drive_files():
    """The Drive `files` resource."""
    return _cached("drive_files", lambda: _drive().files())


def drive_permissions():
    """The Drive `permissions` resource."""
    return _cached("drive_permissions", lambda: _drive().permissions())


def _drive():
    return _cached("drive_service", lambda: _service("drive", "v3"))


def http():
    """
    An http transport private to the calling thread.

    Pass it to every `.execute(http=...)`. Sharing one transport across threads
    corrupts responses; building one per call throws away connection reuse and
    roughly doubles each round trip. One per thread avoids both.
    """
    transport = getattr(_thread_local, "http", None)
    if transport is None:
        transport = google_auth_httplib2.AuthorizedHttp(credentials(), http=httplib2.Http())
        _thread_local.http = transport
    return transport


def reset() -> None:
    """Drop every cached client. For tests and for credential changes."""
    with _build_lock:
        _cache.clear()
    _thread_local.__dict__.pop("http", None)


def _service(name: str, version: str):
    # cache_discovery=False: the on-disk discovery cache is unused here and warns
    # under recent oauth2client-less installs.
    return build(name, version, credentials=credentials(), cache_discovery=False)


def _cached(key: str, factory):
    value = _cache.get(key)
    if value is not None:
        return value
    with _build_lock:
        if key not in _cache:
            _cache[key] = factory()
        return _cache[key]
