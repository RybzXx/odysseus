# ws-01 — Runbook

Covers: one-time setup, what runs on a schedule, and the restore procedure. The restore
section is the one [LOCKED] R1 requires to be followed literally, by someone with no other
context, for the S4 drill to count as done.

**Status: none of this is installed on the phone or in Google yet.** The scripts exist in this
repo (`phone/ws01_*.{sh,py}`, `docs/workstreams/ws-01/apps-script/Code.gs`) but nothing has been
pushed to the device, no crontab line has been added, and no Apps Script project exists. That is
a deliberate, separate step — see "Installing" below — not done as part of writing this runbook.

---

## Prerequisites (one-time, human-only)

1. **rclone Drive remote**, on the phone, in native Termux (not proot):
   ```
   pkg install -y rclone      # already done during S1 research — harmless if repeated
   rclone config
   ```
   Choose `n` (new remote), name it exactly `gdrive`, type `drive`, leave client_id/secret
   blank (use rclone's own), scope `drive` (full access), and complete the browser consent
   screen when prompted. This is the step S1's research could not do headlessly — see
   `research.md` Q3.
   Verify: `rclone lsd gdrive:` should return with no error (an empty listing is fine).
   Then create the working folder: `rclone mkdir gdrive:odysseus-backups`

2. **Confirm the Drive account's own security** (this is what `spec.v2.md`'s R5 resolution
   rests on): 2FA is on, no other person has this Google account's credentials, and check
   `myaccount.google.com/permissions` for any third-party app with Drive scope you don't
   recognize — remove anything unexpected before trusting this backup as private.

## Installing

Push the four scripts to the phone (native Termux home, not proot):
```
py push_file.py phone/ws01_snapshot.py       /data/data/com.termux/files/home/ws01_snapshot.py
py push_file.py phone/ws01_backup_db.sh      /data/data/com.termux/files/home/ws01_backup_db.sh
py push_file.py phone/ws01_backup_files.sh   /data/data/com.termux/files/home/ws01_backup_files.sh
py push_file.py phone/ws01_retention.sh      /data/data/com.termux/files/home/ws01_retention.sh
py push_file.py phone/ws01_heartbeat.sh      /data/data/com.termux/files/home/ws01_heartbeat.sh
```
(`ws01_backup_db.sh` calls `ws01_retention.sh` and `ws01_snapshot.py` by resolving its own
directory, so all five must land in the same directory — `$HOME`, matching this project's
existing `phone/` scripts.)

Then, over SSH (`py ssh_termux.py "chmod +x /data/data/com.termux/files/home/ws01_*.sh"`), and
add to the phone's crontab (`crontab -e`, native Termux):
```
0 * * * *      /data/data/com.termux/files/home/ws01_backup_db.sh
0 3 * * *      /data/data/com.termux/files/home/ws01_backup_files.sh
*/15 * * * *   /data/data/com.termux/files/home/ws01_heartbeat.sh
```

Apps Script (D8):
1. `script.google.com/create`, paste in `apps-script/Code.gs`.
2. Run `ws01_heartbeat.sh` once by hand so `gdrive:odysseus-backups/heartbeat.json` exists,
   then find its Drive file ID (`rclone lsjson gdrive:odysseus-backups/heartbeat.json` — the
   `ID` field) and paste it into `HEARTBEAT_FILE_ID` in Code.gs.
3. Set `ALERT_EMAIL` to the address that should receive scheduler-dead / backup-failing /
   device-offline alerts.
4. Triggers (clock icon, left sidebar) → Add Trigger → function `checkHeartbeat` → Time-driven
   → Minutes timer → Every 15 minutes → Save.
5. Run `checkHeartbeat` once manually from the editor to grant Drive/Mail permissions.

## What runs, on what schedule

| Script | Cadence | Does |
|---|---|---|
| `ws01_backup_db.sh` | hourly | Snapshot `app.db`, verify, compress, upload, then run retention |
| `ws01_backup_files.sh` | daily, 03:00 | Archive `personal_docs/`, `generated_images/`, etc. (D7) |
| `ws01_heartbeat.sh` | every 15 min | Refresh `heartbeat.json` in Drive for the Apps Script checker |
| Apps Script `checkHeartbeat` | every 15 min, on Google's infra | Reads `heartbeat.json`, emails on any stale field |

---

## Restore procedure (the R1 drill)

Follow this on the laptop, using only what's written here. Needs: `rclone` installed and
configured with read access to the same `gdrive:odysseus-backups` remote (or, if rclone isn't
set up on this machine, open [drive.google.com](https://drive.google.com), navigate to the
`odysseus-backups/hourly/` folder, sort by name descending, and download the newest
`app_db_*.zst` file by hand instead of step 1 below), and `zstd` installed
(`winget install zstd` / `choco install zstd`, or use 7-Zip's zstd support).

1. **List and pick the newest snapshot:**
   ```
   rclone lsf gdrive:odysseus-backups/hourly/ | sort | tail -n 1
   ```
   This prints the newest `app_db_<UTC-timestamp>.zst` filename.

2. **Download it:**
   ```
   rclone copyto gdrive:odysseus-backups/hourly/<filename> .\restored_app.db.zst
   ```

3. **Decompress:**
   ```
   zstd -d restored_app.db.zst -o restored_app.db
   ```

4. **Open it and check integrity** (needs Python 3 with the standard library — no extra
   install):
   ```
   py -c "import sqlite3; con = sqlite3.connect('restored_app.db'); print(con.execute('PRAGMA integrity_check').fetchone())"
   ```
   Must print `('ok',)`. Anything else means this snapshot is not usable — go back to step 1
   and try the next-newest one, and separately treat this as a finding (a bad snapshot passed
   this pipeline's own verify step and reached Drive, which should not happen — see
   `ws01_snapshot.py`'s contract).

5. **Compare row counts against what's live on the phone**, to confirm this snapshot is
   recent and complete, not just structurally valid. On the phone (over SSH):
   ```
   py -c "import sqlite3; con = sqlite3.connect('file:/data/data/com.termux/files/home/odysseus-data/app.db?mode=ro', uri=True); print(con.execute('SELECT COUNT(*) FROM chat_messages').fetchone())"
   ```
   On the laptop, against `restored_app.db`, run the same query. The restored count should be
   equal to, or only slightly behind (within roughly one hour's worth of activity — the backup
   cadence), the live count. A restored count far behind the live one, or ahead of it, is a
   finding, not something to explain away.

**The drill is done, per R1, only when steps 1–5 have all been completed by someone using only
this document** — not by whoever wrote the scripts, and not with any extra context beyond what's
written here.

---

## Known limitation carried from S1 (not yet closed)

**Q7 (Doze/App Standby) is still open.** `research.md` could not measure whether a cron-triggered
upload reliably survives Android's Doze mode in a single research pass — that needs a real
overnight observation with this cron installed. Recommended as part of running S4: leave the
phone idle and screen-off overnight after installing the crontab above, then check the next
morning whether `ws01_backup_db.sh`'s hourly runs actually happened
(`cat /data/data/com.termux/files/home/ws01_logs/backup_db.log`) rather than assuming they did.
