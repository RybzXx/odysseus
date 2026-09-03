#!/usr/bin/env python3
"""seed_briefing_fixture.py

Seed a development data directory with the pseudonymised briefing fixture.

The Overview and Organisers modules read four stores that are empty in a fresh
checkout, so both modules render blank locally and their faults cannot be seen.
This writes the fixture produced by ``capture_briefing_fixture.py`` into those
stores, reproducing the live instance's shape -- 157 triaged messages with a
``reason`` and no ``snippet``, 85 of 154 carrying a stored summary, 7 organisers,
10 memories -- without carrying any of its content.

Needs no network, no IMAP server, and no phone. The fixture is committed.

Pre:  --data-dir names a development data directory. The fixture file exists.
Post: ``email_urgency_state_<owner>.json``, ``email_message_index``,
      ``email_summaries``, ``work_organisers`` and ``memory.json`` under that
      directory hold exactly the fixture's contents. Running twice leaves the
      same state as running once.
Inv:  a directory holding real mail is never written to. The check is a
      positive test for fixture provenance, not an absence-of-data test: every
      fixture address ends in the reserved domain, so anything else present is
      real and the run aborts.

Usage:
    python scripts/seed_briefing_fixture.py
    python scripts/seed_briefing_fixture.py --data-dir /tmp/odysseus-dev
    python scripts/seed_briefing_fixture.py --clear     # remove seeded rows
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "briefing_shape.json"

# Must match capture_briefing_fixture.ALIAS_DOMAIN. Every address the fixture
# carries ends in it, which is what makes real mail detectable.
ALIAS_DOMAIN = "example.invalid"

# Refusing to touch the live instance's directory is worth stating explicitly
# rather than relying on the address check alone.
PROTECTED_DIRS = ("/data/data/com.termux/files/home/odysseus-data",)


class RealMailPresent(Exception):
    """The target directory holds mail the fixture did not put there."""


def _resolve_data_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    from src.constants import DATA_DIR
    return Path(DATA_DIR).resolve()


def _assert_safe_target(data_dir: Path) -> None:
    """Abort unless the target holds only fixture-shaped mail, or no mail.

    Post: returns only when seeding cannot destroy real correspondence.
    """
    normalised = str(data_dir).replace("\\", "/").rstrip("/")
    for protected in PROTECTED_DIRS:
        if normalised.endswith(protected.rstrip("/")):
            raise RealMailPresent(
                f"{data_dir} is the live instance's data directory. Refusing."
            )

    db_path = data_dir / "scheduled_emails.db"
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path))
    try:
        try:
            rows = conn.execute(
                "SELECT from_address FROM email_message_index "
                "WHERE from_address IS NOT NULL AND from_address != ''"
            ).fetchall()
        except sqlite3.OperationalError:
            return  # table absent: nothing to protect

        foreign = [r[0] for r in rows if ALIAS_DOMAIN not in (r[0] or "")]
        if foreign:
            raise RealMailPresent(
                f"{db_path} holds {len(foreign)} message(s) from real addresses "
                f"(e.g. {foreign[0]!r}). Refusing to seed over real mail. "
                f"Use --data-dir to point at a scratch directory."
            )
    finally:
        conn.close()


def _ensure_schema(data_dir: Path) -> None:
    """Create both stores' schemas in the target directory, using the app's own DDL.

    ``work_organisers`` postdates some existing development databases, and a
    fresh directory has no email cache at all, so neither module can be
    exercised until both exist. Both are created by calling the application's
    own definitions rather than restating them here -- a copied CREATE TABLE
    drifts from the real schema the moment a column is added, and the fixture
    would then seed a shape the app no longer reads.
    """
    import core.database as cdb
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{(data_dir / 'app.db').as_posix()}")
    try:
        cdb.Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    # _init_scheduled_db reads a module-level path constant, so point it at the
    # target directory for the duration of the call and put it back after.
    from routes import email_helpers

    original = email_helpers.SCHEDULED_DB
    email_helpers.SCHEDULED_DB = data_dir / "scheduled_emails.db"
    try:
        email_helpers._init_scheduled_db()
    finally:
        email_helpers.SCHEDULED_DB = original


def _write_table(conn: sqlite3.Connection, table: str, dump: Dict[str, Any]) -> int:
    """Replace the fixture's rows in one table. Idempotent by primary key."""
    cols: List[str] = dump.get("columns") or []
    rows: List[List[Any]] = dump.get("rows") or []
    if not cols or not rows:
        return 0

    placeholders = ", ".join("?" for _ in cols)
    column_list = ", ".join(f'"{c}"' for c in cols)
    conn.executemany(
        f'INSERT OR REPLACE INTO "{table}" ({column_list}) VALUES ({placeholders})',
        [list(r) for r in rows],
    )
    return len(rows)


def _seed_sqlite(data_dir: Path, fixture: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}

    sched = data_dir / "scheduled_emails.db"
    conn = sqlite3.connect(str(sched))
    try:
        for table in ("email_message_index", "email_summaries"):
            try:
                counts[table] = _write_table(conn, table, fixture.get(table) or {})
            except sqlite3.OperationalError as exc:
                counts[table] = 0
                print(f"  skipped {table}: {exc}")
        conn.commit()
    finally:
        conn.close()

    app_db = data_dir / "app.db"
    conn = sqlite3.connect(str(app_db))
    try:
        counts["work_organisers"] = _write_table(
            conn, "work_organisers", fixture.get("work_organisers") or {}
        )
        conn.commit()
    finally:
        conn.close()

    return counts


def _seed_files(data_dir: Path, fixture: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}

    for filename, state in (fixture.get("urgency_states") or {}).items():
        (data_dir / filename).write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
        counts[filename] = len(state.get("per_uid") or {})

    memories = fixture.get("memories") or []
    (data_dir / "memory.json").write_text(
        json.dumps(memories, indent=2), encoding="utf-8"
    )
    counts["memory.json"] = len(memories)
    return counts


def _clear(data_dir: Path, fixture: Dict[str, Any]) -> Dict[str, int]:
    """Remove exactly what seeding added, leaving anything else untouched."""
    counts: Dict[str, int] = {}

    index = fixture.get("email_message_index") or {}
    cols = index.get("columns") or []
    sched = data_dir / "scheduled_emails.db"
    if sched.exists() and cols:
        conn = sqlite3.connect(str(sched))
        try:
            cur = conn.execute(
                "DELETE FROM email_message_index WHERE from_address LIKE ?",
                (f"%{ALIAS_DOMAIN}",),
            )
            counts["email_message_index"] = cur.rowcount
            mids = [r[0] for r in (fixture.get("email_summaries") or {}).get("rows", [])]
            if mids:
                conn.executemany(
                    "DELETE FROM email_summaries WHERE message_id = ?",
                    [(m,) for m in mids],
                )
                counts["email_summaries"] = len(mids)
            conn.commit()
        except sqlite3.OperationalError as exc:
            print(f"  skipped sqlite clear: {exc}")
        finally:
            conn.close()

    app_db = data_dir / "app.db"
    org = fixture.get("work_organisers") or {}
    if app_db.exists() and org.get("rows"):
        conn = sqlite3.connect(str(app_db))
        try:
            ids = [r[0] for r in org["rows"]]
            conn.executemany("DELETE FROM work_organisers WHERE id = ?", [(i,) for i in ids])
            counts["work_organisers"] = len(ids)
            conn.commit()
        except sqlite3.OperationalError as exc:
            print(f"  skipped organiser clear: {exc}")
        finally:
            conn.close()

    for filename in (fixture.get("urgency_states") or {}):
        target = data_dir / filename
        if target.exists():
            target.unlink()
            counts[filename] = 1

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    parser.add_argument("--data-dir", default=None,
                        help="target data directory (default: src.constants.DATA_DIR)")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--clear", action="store_true",
                        help="remove seeded rows instead of writing them")
    args = parser.parse_args()

    if not args.fixture.exists():
        print(f"No fixture at {args.fixture}. Run capture_briefing_fixture.py first.",
              file=sys.stderr)
        return 1

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    data_dir = _resolve_data_dir(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    try:
        _assert_safe_target(data_dir)
    except RealMailPresent as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 1

    if args.clear:
        counts = _clear(data_dir, fixture)
        print(f"Cleared fixture data from {data_dir}")
    else:
        _ensure_schema(data_dir)
        counts = {**_seed_sqlite(data_dir, fixture), **_seed_files(data_dir, fixture)}
        print(f"Seeded {data_dir}")

    for name, count in counts.items():
        print(f"  {name}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
