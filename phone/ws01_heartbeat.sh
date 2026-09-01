#!/data/data/com.termux/files/usr/bin/bash
#
# ws-01 D8 (phone side): maintain one live heartbeat.json in Drive carrying three
# independent signals, so a single Apps Script trigger can still distinguish
# L1's three cases (scheduler dead / backup failing / device offline) from one
# file read. Runs every 15 min, piggybacking the cadence
# ensure_supervisor.sh already uses (see docs/workstreams/ws-01/research.md Q6).
#
# heartbeat.json is a single live pointer, not a versioned backup -- it is
# overwritten in place on every run and carries no retention of its own; R4's
# versioning requirement applies to the DB/file backups (ws01_backup_db.sh /
# ws01_backup_files.sh), not to this liveness signal.
#
# Contract
#     Pre:  DB exists and is readable (read-only connection only).
#     Post: REMOTE/heartbeat.json reflects, best-effort: this run's own
#           wall-clock time (device_online_at), the live db's most recent
#           task_runs timestamp as a scheduler-liveness proxy (scheduler_tick_at,
#           empty string if unreadable), and the last successful backup's
#           timestamp from ws01_backup_db.sh's own status file
#           (backup_success_at, empty string if none/failed).
#     Inv:  never blocks on a missing status file or an unreadable db -- a
#           missing signal is reported as an empty field, not a script failure,
#           so one broken signal never prevents the other two from being
#           reported.

set -uo pipefail

DATA_DIR="/data/data/com.termux/files/home/odysseus-data"
DB="$DATA_DIR/app.db"
WORKDIR="/data/data/com.termux/files/home/ws01_work"
STATUS_FILE="$WORKDIR/last_backup_status.json"
REMOTE="gdrive:odysseus-backups"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "$WORKDIR"

SCHEDULER_TICK="$(python3 -c "
import sqlite3
try:
    con = sqlite3.connect('file:$DB?mode=ro', uri=True)
    row = con.execute('SELECT MAX(created_at) FROM task_runs').fetchone()
    print(row[0] if row and row[0] else '')
except Exception:
    print('')
" 2>/dev/null)"

BACKUP_SUCCESS_AT=""
if [ -f "$STATUS_FILE" ]; then
    BACKUP_SUCCESS_AT="$(python3 -c "
import json
try:
    d = json.load(open('$STATUS_FILE'))
    print(d['at'] if d.get('ok') else '')
except Exception:
    print('')
" 2>/dev/null)"
fi

HEARTBEAT_TMP="$WORKDIR/heartbeat.json.tmp"
python3 -c "
import json
json.dump({
    'device_online_at': '$NOW',
    'scheduler_tick_at': '$SCHEDULER_TICK',
    'backup_success_at': '$BACKUP_SUCCESS_AT',
}, open('$HEARTBEAT_TMP', 'w'))
"
mv "$HEARTBEAT_TMP" "$WORKDIR/heartbeat.json"

rclone copyto "$WORKDIR/heartbeat.json" "$REMOTE/heartbeat.json" --drive-use-trash=false
