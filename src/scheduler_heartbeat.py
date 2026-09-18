"""Persist evidence of a completed scheduler poll, independently of task runs."""

import os
from datetime import datetime, timezone

from core.atomic_io import atomic_write_json
from src.constants import DATA_DIR


def record_scheduler_poll():
    """Write only after the scheduler completes its poll. The publisher never refreshes it."""
    atomic_write_json(os.path.join(DATA_DIR, "scheduler_heartbeat.json"), {
        "at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
    })
