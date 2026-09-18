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
#           wall-clock time (device_online_at), the scheduler's own
#           completed-poll timestamp (scheduler_tick_at, empty if unreadable), and the last successful backup's
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

# Build independent signals. Only the scheduler can refresh its own timestamp.
python3 /data/data/com.termux/files/home/ws01_heartbeat.py \
    --data-dir "$DATA_DIR" --status-file "$STATUS_FILE" \
    --output "$WORKDIR/heartbeat.json" || exit 1

rclone copyto "$WORKDIR/heartbeat.json" "$REMOTE/heartbeat.json" --drive-use-trash=false
