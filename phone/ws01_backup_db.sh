#!/data/data/com.termux/files/usr/bin/bash
#
# ws-01 D1: hourly database backup. Runs in native Termux (D5 -- avoids proot's
# ptrace overhead; ODYSSEUS_DATA_DIR already lives outside the rootfs, so nothing
# here needs `proot-distro login`).
#
# R2 is satisfied by construction, not by error handling: this is a separate cron
# process from Odysseus's own scheduler, so nothing this script does -- slow,
# failing, or crashing -- can block or crash a scheduler tick. What this script IS
# responsible for is never corrupting the live db (see ws01_snapshot.py, read-only
# throughout) and never promoting a bad snapshot (R3: temp name until verified,
# fsync'd, integrity-checked, only then uploaded under its real name).
#
# Contract
#     Pre:  DB exists and is readable. RCLONE remote configured (see RUNBOOK.md --
#           this is a human, one-time OAuth step; not something this script can do).
#     Post: on success, exactly one new object named app_db_<timestamp>.zst exists
#           under REMOTE/hourly/, and last_backup_status.json says ok=true.
#     Inv:  every local temp file this script creates is removed before exit,
#           success or failure. Never touches DB except through a read-only
#           connection (delegated to ws01_snapshot.py).
#
# Blame
#     "snapshot/verify failed" -> read ws01_snapshot.py's own error; the live db
#         itself is never at risk (see its Inv), so this is always about the
#         temp copy, not data loss.
#     "rclone upload failed"  -> almost always the Drive remote's auth/quota;
#         check `rclone lsd REMOTE` by hand first.

set -uo pipefail

DATA_DIR="/data/data/com.termux/files/home/odysseus-data"
DB="$DATA_DIR/app.db"
WORKDIR="/data/data/com.termux/files/home/ws01_work"
LOGDIR="/data/data/com.termux/files/home/ws01_logs"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE="gdrive:odysseus-backups"   # must already exist -- see RUNBOOK.md prerequisites
STATUS_FILE="$WORKDIR/last_backup_status.json"

mkdir -p "$WORKDIR" "$LOGDIR"
LOG="$LOGDIR/backup_db.log"
TS="$(date -u +%Y%m%dT%H%M%SZ)"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

write_status() {
    local ok_json="$1" detail="$2"
    local detail_json
    detail_json="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$detail")"
    # write-then-rename: the heartbeat script (a separate process) never sees a
    # half-written status file.
    printf '{"ok": %s, "at": "%sZ", "detail": %s}\n' "$ok_json" "$(date -u +%Y-%m-%dT%H:%M:%S)" "$detail_json" \
        > "$STATUS_FILE.tmp" && mv "$STATUS_FILE.tmp" "$STATUS_FILE"
}

fail() {
    log "FAIL: $1"
    write_status false "$1"
    exit 1
}

VACUUM_TMP="$WORKDIR/app.db.$TS.vacuum.tmp"
SNAP_RESULT="$(python3 "$SCRIPT_DIR/ws01_snapshot.py" "$DB" "$VACUUM_TMP" 2>&1)"
SNAP_OK="$(printf '%s' "$SNAP_RESULT" | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("ok", False))
except Exception:
    print(False)' 2>/dev/null)"
if [ "$SNAP_OK" != "True" ]; then
    rm -f "$VACUUM_TMP"
    fail "snapshot/verify failed: $SNAP_RESULT"
fi
log "snapshot verified: $SNAP_RESULT"

COMPRESSED="$WORKDIR/app.db.$TS.zst"
if ! zstd -19 -q -f -o "$COMPRESSED" "$VACUUM_TMP"; then
    rm -f "$VACUUM_TMP" "$COMPRESSED"
    fail "compression failed"
fi
rm -f "$VACUUM_TMP"

REMOTE_NAME="app_db_${TS}.zst"
if ! rclone copyto "$COMPRESSED" "$REMOTE/hourly/$REMOTE_NAME" --drive-use-trash=false; then
    rm -f "$COMPRESSED"
    fail "rclone upload failed"
fi
rm -f "$COMPRESSED"

log "OK: uploaded $REMOTE_NAME"
write_status true "uploaded $REMOTE_NAME"

if ! "$SCRIPT_DIR/ws01_retention.sh" >> "$LOG" 2>&1; then
    log "retention step reported a problem (see above) -- this hour's backup still succeeded, uploaded and verified"
fi
