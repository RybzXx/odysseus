# ws-01 — Deployment checklist

Reference artifact for installing the backup+liveness pipeline (`RUNBOOK.md`). Disposition is
updated in place as work happens; nothing here is silently dropped.

| # | Item | Obligation | Owner | Done-condition | Disposition |
|---|---|---|---|---|---|
| 1.1 | Configure `gdrive` rclone remote | MUST | human (auth) + agent (wizard) | `rclone lsd gdrive:` succeeds, `gdrive:odysseus-backups` exists | **done** — user completed OAuth consent (laptop `rclone authorize` + a second confirmation on the phone), agent created the remote non-interactively via `rclone config create ... token=...`, verified with a real `rclone lsd gdrive:` listing |
| 1.2 | Verify Drive account posture (2FA, no shared access, no unexpected 3rd-party Drive-scope apps) | SHOULD | human | `myaccount.google.com/permissions` reviewed | pending |
| 1.3 | Push 5 scripts to phone | MUST | agent | files present at `$HOME`, content matches repo | **done** — sha256-verified by `push_file.py`'s own postcondition check |
| 1.4 | `chmod +x` the 5 scripts | MUST | agent | executable bit set | **done** — set via `push_file.py`'s mode arg, confirmed with `ls -l` |
| 1.5 | Install 3 crontab lines | MUST | agent | `crontab -l` shows the 3 new lines | **done** — confirmed alongside the pre-existing `ensure_supervisor.sh` line, no duplicates |
| 1.6 | First manual run + verify | MUST | agent | `ws01_backup_db.sh` exits 0, object lands in Drive, status file says `ok=true` | **done** — exit 0, status file `ok=true`, `app_db_20260901T111359Z.zst` confirmed present via `rclone lsf` |
| 1.13 (new) | rclone's shared `client_id` is being retired during 2026 | SHOULD | human, before it breaks | rclone itself printed this warning on the live upload (not something S1 anticipated) — create a dedicated Google Cloud OAuth client_id and reconfigure `gdrive` before the shared one stops working | pending — no date given by rclone beyond "during 2026" |
| 1.7 | Create Apps Script project | MUST | human (browser + Google login) | project exists with `Code.gs` pasted in, IDs filled | pending |
| 1.8 | Install Apps Script trigger | MUST | human | Triggers panel shows `checkHeartbeat` on 15-min timer | pending |
| 1.9 | Grant Apps Script permissions | MUST | human (one-click consent, unscriptable) | manual run completes with no pending dialog | pending |
| 1.10 | End-to-end liveness test | SHOULD | human+agent | kill/restore heartbeat source, alert then recovery email arrive | blocked (needs 1.7-1.9) |
| 1.11 | S4 restore drill | MUST — this is R1's actual definition of done | human, runbook only | integrity_check ok, row counts match within drift window | blocked (needs 1.1, 1.5, 1.6) |
| 1.12 | Overnight Doze observation | SHOULD — closes Q7 | passive | `backup_db.log` shows unbroken hourly entries overnight | blocked (needs 1.5) |
