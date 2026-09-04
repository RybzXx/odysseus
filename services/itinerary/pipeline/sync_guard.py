"""
BilWeekend — Sheets Pull Guard
Wraps the Sheets → local pull so a failed pull can never leave data/ half-written,
and so two pulls can never interleave. Framework-free: usable from the CLI, the
desktop GUI and the web app alike.
"""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
import threading
from pathlib import Path

from services.itinerary.pipeline import config
from services.itinerary.pipeline.sheets_sync import sync_all_from_sheets_to_local

_pull_lock = threading.Lock()


def _force_rmtree(path) -> None:
    """
    Delete a tree, clearing read-only flags first.

    Several directories under data/ carry the Windows read-only attribute;
    copytree propagates it to the copy and a plain rmtree then fails with
    PermissionError. Clearing up front rather than in an error handler keeps this
    to one code path: rmtree's handler keyword was renamed in Python 3.12, and
    the deployed Python version is not pinned.
    """
    root = Path(path)
    if not root.exists():
        return
    for entry in (root, *root.rglob("*")):
        try:
            os.chmod(entry, entry.stat().st_mode | stat.S_IWUSR)
        except OSError:
            pass  # best effort; rmtree reports anything that actually blocks it
    shutil.rmtree(root)


class SyncAlreadyRunning(RuntimeError):
    """A pull was requested while another pull was still in progress."""


def sync_all_from_sheets_atomic() -> None:
    """
    Pull every Sheets tab into data/, all-or-nothing.

    Pre:  service is a built Sheets API client; config.DATA_DIR exists.
    Post: on success data/ mirrors the Sheets; on failure data/ is identical to
          its pre-call state and the original exception is re-raised unchanged.
    Invariant: at most one pull runs at a time, process-wide.
    """
    if not _pull_lock.acquire(blocking=False):
        raise SyncAlreadyRunning("A sync is already running. Try again in a moment.")

    snapshot_dir = None
    try:
        snapshot_dir = _snapshot_data_dir()
        try:
            sync_all_from_sheets_to_local()
        except BaseException:
            _restore_data_dir(snapshot_dir)
            raise
    finally:
        if snapshot_dir is not None:
            _force_rmtree(snapshot_dir)
        _pull_lock.release()


def _snapshot_data_dir() -> str:
    """Copy data/ into a fresh scratch directory beside it and return that directory."""
    data_dir = Path(config.DATA_DIR)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    # Deliberately a sibling of data/ rather than the system temp dir: same
    # filesystem, and cleanup does not depend on temp-dir permissions, which are
    # not guaranteed to allow recursive delete on every host.
    holder = tempfile.mkdtemp(prefix=".data_snapshot_", dir=os.path.dirname(data_dir))
    copy_root = Path(holder) / data_dir.name
    shutil.copytree(data_dir, copy_root)

    # A snapshot with no JSON in it cannot restore anything — refuse before the
    # pull starts deleting template files.
    if not any(copy_root.rglob("*.json")):
        _force_rmtree(holder)
        raise RuntimeError(f"Snapshot of {data_dir} contains no JSON files; refusing to sync.")

    return holder


def _restore_data_dir(snapshot_dir: str) -> None:
    """
    Put data/ back the way _snapshot_data_dir found it.

    Copies over the top instead of clearing first: on Windows a tree removed with
    rmtree can linger in a pending-delete state long enough for the immediate
    re-create to fail, which would leave data/ missing altogether.
    """
    data_dir = Path(config.DATA_DIR)
    copy_root = Path(snapshot_dir) / data_dir.name

    shutil.copytree(copy_root, data_dir, dirs_exist_ok=True)

    # Drop anything the failed pull added that the snapshot does not have.
    for path in sorted(data_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if (copy_root / path.relative_to(data_dir)).exists():
            continue
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            _force_rmtree(path)
