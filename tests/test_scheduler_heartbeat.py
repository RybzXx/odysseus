"""Scheduler activity and task activity are separate signals."""
import json
import sqlite3

from phone.ws01_heartbeat import collect_heartbeat


def test_idle_scheduler_has_a_tick_without_task_runs(tmp_path):
    with sqlite3.connect(tmp_path / "app.db") as conn:
        conn.execute("CREATE TABLE task_runs(started_at TEXT)")
    (tmp_path / "scheduler_heartbeat.json").write_text(json.dumps({"at": "2026-09-18T08:00:00Z"}))
    backup = tmp_path / "backup.json"
    backup.write_text(json.dumps({"ok": True, "at": "2026-09-18T07:30:00Z"}))
    result = collect_heartbeat(tmp_path, backup)
    assert result["scheduler_tick_at"] == "2026-09-18T08:00:00+00:00"
    assert result["last_task_started_at"] == ""
    assert result["backup_success_at"] == "2026-09-18T07:30:00+00:00"
    assert collect_heartbeat(tmp_path, backup)["scheduler_tick_at"] == result["scheduler_tick_at"]


def test_task_history_does_not_fabricate_a_scheduler_tick(tmp_path):
    with sqlite3.connect(tmp_path / "app.db") as conn:
        conn.execute("CREATE TABLE task_runs(started_at TEXT)")
        conn.execute("INSERT INTO task_runs VALUES ('2026-09-18 08:00:00')")
    result = collect_heartbeat(tmp_path, tmp_path / "missing")
    assert result["scheduler_tick_at"] == ""
    assert result["last_task_started_at"] == "2026-09-18T08:00:00+00:00"
    assert result["backup_success_at"] == ""


def test_scheduler_writes_its_own_timestamp(tmp_path, monkeypatch):
    from src import scheduler_heartbeat
    monkeypatch.setattr(scheduler_heartbeat, "DATA_DIR", str(tmp_path))
    scheduler_heartbeat.record_scheduler_poll()
    assert collect_heartbeat(tmp_path, tmp_path / "missing")["scheduler_tick_at"]
