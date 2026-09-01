#!/usr/bin/env python3
"""ws-01 R3: VACUUM INTO a temp file from the live app.db, then verify before anyone
trusts it. Never opens the source for writing -- connects read-only throughout.

Contract
    Pre:  argv[1] is a live, readable sqlite db. argv[2] does not already contain
          something the caller cares about (this script deletes it if present, since
          VACUUM INTO refuses to write over an existing file).
    Post: exit 0 and dest exists, is a valid sqlite db, fsync'd, PRAGMA integrity_check
          = ok, and its table count is not less than the source's -- or exit 1 and dest
          is not to be trusted (may not exist, or may be a partial/invalid file left by
          a kill mid-run; the caller must not promote it either way).
    Inv:  the source is only ever read. A SIGKILL of this process can only corrupt
          dest, never the live database.

Measured on this device (see docs/workstreams/ws-01/research.md, Q2): a SIGKILLed
VACUUM INTO leaves a file that exists on disk but fails to open as a valid sqlite
database -- exactly the case this script's own verify step is built to catch, so a
future caller re-running after a kill sees the same "untrusted, re-run" signal whether
the process died or completed and failed verification.
"""
import json
import os
import sqlite3
import sys


def fail(message):
    print(json.dumps({"ok": False, "error": message}))
    return 1


def main():
    if len(sys.argv) != 3:
        return fail("usage: ws01_snapshot.py <source_db> <dest_tmp_path>")
    src, dest = sys.argv[1], sys.argv[2]

    if os.path.exists(dest):
        os.remove(dest)

    try:
        con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        con.execute("VACUUM INTO ?", (dest,))
        con.close()
    except Exception as e:
        return fail(f"vacuum_into failed: {e}")

    try:
        fd = os.open(dest, os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
    except Exception as e:
        return fail(f"fsync failed: {e}")

    try:
        out_con = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
        integrity = out_con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            return fail(f"integrity_check={integrity}")
        out_tables = out_con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        out_con.close()
    except Exception as e:
        return fail(f"verify failed: {e}")

    try:
        src_con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        src_tables = src_con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        src_con.close()
    except Exception as e:
        return fail(f"source recheck failed: {e}")

    if out_tables < src_tables:
        return fail(f"table count regressed: src={src_tables} out={out_tables}")

    print(json.dumps({"ok": True, "dest": dest, "table_count": out_tables}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
