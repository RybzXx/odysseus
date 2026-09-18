"""Build independent heartbeat signals without changing the application database."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from datetime import datetime, timezone


def read_json(path):
    try:
        value = Path(path).read_text(encoding="utf-8")
        result = json.loads(value)
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def collect_heartbeat(data_dir, status_file):
    """Missing signals stay missing. One failed read cannot erase another signal."""
    data_dir = Path(data_dir)
    last_task = ""
    try:
        with sqlite3.connect((data_dir / "app.db").resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as conn:
            last_task = timestamp(conn.execute("SELECT MAX(started_at) FROM task_runs").fetchone()[0])
    except sqlite3.Error:
        pass
    backup = read_json(status_file)
    return {
        "device_online_at": datetime.now(timezone.utc).isoformat(),
        "scheduler_tick_at": timestamp(read_json(data_dir / "scheduler_heartbeat.json").get("at")),
        "last_task_started_at": last_task,
        "backup_success_at": timestamp(backup.get("at")) if backup.get("ok") else "",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=output.parent, prefix=output.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(collect_heartbeat(args.data_dir, args.status_file), stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    main()
