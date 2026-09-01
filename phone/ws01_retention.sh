#!/data/data/com.termux/files/usr/bin/bash
#
# ws-01 D2/R4: filename-based retention over the hourly snapshot stream --
# 24 hourly, 14 daily, 6 monthly, satisfying spec.v2 without needing separate
# hourly/daily/monthly upload paths: one stream, three overlapping keep-windows,
# union kept, everything else deleted.
#
# R4: this only ever deletes snapshots outside the keep-set. It never overwrites
# or touches a kept snapshot, so corruption discovered N days late is still
# recoverable from whichever daily/monthly copy predates it.
#
# --drive-use-trash=false on every delete: rclone's Drive backend defaults to
# moving deletes into Drive's Trash (measured, docs/workstreams/ws-01/research.md
# Q3) rather than freeing them immediately, which would make "what's actually
# live" ambiguous under casual inspection -- this keeps R4's filename-based
# retention unambiguous.
#
# Contract
#     Pre:  REMOTE/hourly/ contains zero or more app_db_<UTC-timestamp>.zst files.
#     Post: exactly the union of (24 most recent) + (newest-per-day, last 14
#           distinct days) + (newest-per-month, last 6 distinct months) remains;
#           everything else in REMOTE/hourly/ is deleted.
#     Inv:  a file matching the keep-set is never deleted, even if this script is
#           re-run repeatedly or run out of order relative to ws01_backup_db.sh.

set -uo pipefail

REMOTE="gdrive:odysseus-backups"

python3 - "$REMOTE" <<'PYEOF'
import re
import subprocess
import sys
import datetime

remote = sys.argv[1]

out = subprocess.run(
    ["rclone", "lsf", f"{remote}/hourly/"],
    capture_output=True, text=True, check=True,
).stdout

pattern = re.compile(r"app_db_(\d{8}T\d{6}Z)\.zst")
entries = []
for line in out.splitlines():
    m = pattern.match(line.strip())
    if not m:
        continue
    ts = datetime.datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ")
    entries.append((ts, line.strip()))
entries.sort(key=lambda e: e[0], reverse=True)  # newest first

keep = set()

for ts, name in entries[:24]:
    keep.add(name)

seen_days = set()
for ts, name in entries:
    day = ts.date()
    if day in seen_days:
        continue
    if len(seen_days) >= 14:
        break
    seen_days.add(day)
    keep.add(name)

seen_months = set()
for ts, name in entries:
    month = (ts.year, ts.month)
    if month in seen_months:
        continue
    if len(seen_months) >= 6:
        break
    seen_months.add(month)
    keep.add(name)

to_delete = [name for ts, name in entries if name not in keep]

for name in to_delete:
    print(f"deleting {name}")
    subprocess.run(
        ["rclone", "deletefile", f"{remote}/hourly/{name}", "--drive-use-trash=false"],
        check=False,
    )

print(f"kept {len(keep)} of {len(entries)} snapshots")
PYEOF
