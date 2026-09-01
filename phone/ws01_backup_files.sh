#!/data/data/com.termux/files/usr/bin/bash
#
# ws-01 D7: daily archive of user-referenced flat files that live outside app.db
# (documents / gallery_images / project_links rows point at these -- see
# docs/workstreams/ws-01/research.md Q8). A DB-only backup leaves a restored row
# pointing at a file nobody saved; this closes that gap. Deliberately daily, not
# hourly -- these directories change far less often than app.db and D3 (Wi-Fi
# only, metered mobile data) favors a lighter cadence here.
#
# Regenerable caches (fastembed_cache, logs, tts_cache, emoji_cache,
# email_urgency_cache, cache) are excluded on purpose -- see research.md Q8 for
# why each is safe to exclude.
#
# Contract
#     Pre:  DATA_DIR exists. RCLONE remote configured (see RUNBOOK.md).
#     Post: on success, one new files_<timestamp>.tar.zst exists under
#           REMOTE/daily-files/, and at most 14 remain after retention.
#     Inv:  same temp-then-promote shape as ws01_backup_db.sh (R3) -- a killed
#           run never leaves something that could be mistaken for a complete
#           archive.

set -uo pipefail

DATA_DIR="/data/data/com.termux/files/home/odysseus-data"
WORKDIR="/data/data/com.termux/files/home/ws01_work"
LOGDIR="/data/data/com.termux/files/home/ws01_logs"
REMOTE="gdrive:odysseus-backups"

mkdir -p "$WORKDIR" "$LOGDIR"
LOG="$LOGDIR/backup_files.log"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

DIRS="personal_docs personal_uploads generated_images mail-attachments uploads deep_research projects skills bilweekend hwfit"

cd "$DATA_DIR" || { log "FAIL: cannot cd to $DATA_DIR"; exit 1; }

EXISTING=""
for d in $DIRS; do
    [ -d "$d" ] && EXISTING="$EXISTING $d"
done

if [ -z "$EXISTING" ]; then
    log "nothing to archive -- none of the expected directories exist"
    exit 0
fi

TMP_TAR="$WORKDIR/files.$TS.tar.zst.tmp"
# shellcheck disable=SC2086 -- EXISTING is an intentionally unquoted word list of dir names
if ! tar -cf - $EXISTING | zstd -19 -q -o "$TMP_TAR"; then
    rm -f "$TMP_TAR"
    log "FAIL: tar/compress failed"
    exit 1
fi

FINAL_TAR="$WORKDIR/files.$TS.tar.zst"
mv "$TMP_TAR" "$FINAL_TAR"

REMOTE_NAME="files_${TS}.tar.zst"
if ! rclone copyto "$FINAL_TAR" "$REMOTE/daily-files/$REMOTE_NAME" --drive-use-trash=false; then
    rm -f "$FINAL_TAR"
    log "FAIL: upload failed"
    exit 1
fi
rm -f "$FINAL_TAR"
log "OK: uploaded $REMOTE_NAME"

python3 - "$REMOTE" <<'PYEOF'
import re, subprocess, sys
remote = sys.argv[1]
out = subprocess.run(["rclone", "lsf", f"{remote}/daily-files/"], capture_output=True, text=True, check=True).stdout
pattern = re.compile(r"files_(\d{8}T\d{6}Z)\.tar\.zst")
entries = []
for line in out.splitlines():
    m = pattern.match(line.strip())
    if m:
        entries.append((m.group(1), line.strip()))
entries.sort(reverse=True)
for _, name in entries[14:]:  # D2's daily count -- keep the newest 14, drop the rest
    subprocess.run(["rclone", "deletefile", f"{remote}/daily-files/{name}", "--drive-use-trash=false"], check=False)
PYEOF
