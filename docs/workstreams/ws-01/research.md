# ws-01 — S1 Research

Stage: S1 (research, read-only). Target of this stage: resolve Q1–Q8 from `spec.md`. This file is
the only file this stage wrote.

## LOCKED-item contradiction — flag first

**R5's factual premise is partially false as of today.** R5 says: "The database contains customer
PII (names, emails, phone numbers, request text from the Bil Weekend worklist)." Live schema
inspection of the actually-live `app.db` (see Q5/Q8 and Measurements) shows **no** `bookings`,
`contacts`, `curated_requests`, `queue_requests`, or any other Bil Weekend customer/booking table
exists locally. Per `SYSTEM_RECORD.md` Rev S (SOURCED) and confirmed live (MEASURED), that PII is
fetched at request time from a separate Supabase Postgres project via PostgREST and is **not**
stored in Odysseus's SQLite database. The only Bil-Weekend-adjacent local table is
`operations_notes` (1 row) — agent-authored ops notes, not customer records.

This does **not** make R5 moot, and I am not treating it as a workaround-and-move-on: the live
`app.db` contains something arguably more sensitive than the PII R5 anticipated — the
`email_accounts` table (4 rows) stores IMAP/SMTP passwords and OAuth access/refresh tokens **in
plaintext columns**, and `api_tokens`/`provider_auth_sessions`/`integrations`/`webhooks` are
credential-shaped tables (mostly empty today, structurally capable of holding secrets). `.env`
(guest-side) also holds a live Supabase service-role key. So R5's *spirit* — "encrypt client-side,
or explicitly accept Drive as a trust boundary, silence is not an option" — still fully applies,
and if anything the bar is higher than R5's own text implies. This is reported here per protocol
("stop-and-flag, not absorbed into a workaround"); the encryption decision in Q5 treats the
database as containing real account credentials, not just customer PII, and is stricter as a
result.

No other [LOCKED] item was found contradicted by anything measured this pass.

---

## What's live, verified directly (not assumed)

- `ODYSSEUS_DATA_DIR=/data/data/com.termux/files/home/odysseus-data` — MEASURED, read from
  `/root/odysseus/.env` inside the proot guest.
- The Termux-home copy is the live one: `app.db` there is 2,310,144 bytes, mtime continuously
  advancing (last write at measurement time). The in-rootfs fallback copy
  (`/root/odysseus/data/app.db`) is 757,760 bytes and stale (last write hours earlier, smaller).
  MEASURED via `ls -la` + `date` on both paths.
- One `uvicorn app:app` process (pid 1561) plus five MCP-server child processes
  (`image_gen_server.py`, `memory_server.py`, `rag_server.py`, `email_server.py`,
  `ops_server.py`), all children of the same process tree, plus `chroma` running standalone on
  port 8100. All are potential independent SQLite connections against `app.db` — MEASURED via
  `ps -ef`. This matters for Q2: there is more than one process capable of writing concurrently,
  not just the one obvious uvicorn process.
- `journal_mode = delete` (rollback journal, **not** WAL), `busy_timeout = 5000` ms — MEASURED via
  a read-only `sqlite3.connect(..., mode=ro)` PRAGMA query against the live file. No `-wal`/`-shm`
  files present, consistent with delete-mode.
- Real `app.db` size: 2,310,144 bytes. Whole data dir: 232 MB, of which `fastembed_cache` alone is
  217 MB (a re-derivable downloaded ONNX model — see Q8). `chroma/` is 3.8 MB. — all MEASURED.

---

## Q1 · Transport

**Decision: keep [DEFAULT] D1 — snapshot (`VACUUM INTO`) + compress + encrypt + `rclone` to a
Drive remote, hourly. Do not adopt Litestream.**

Evidence:
- Litestream v0.3.13 was actually installed and run on this device (MEASURED): it installs and
  runs cleanly *inside* the proot Ubuntu guest (`litestream version` → `v0.3.13`), but the
  extracted glibc binary run directly in **native** Termux crashes immediately
  (`Unknown signal 31`, i.e. it cannot run outside the proot glibc environment). Litestream is
  therefore proot-only on this device, which directly conflicts with **[DEFAULT] D5** (avoid
  proot's ptrace overhead for syscall-heavy I/O like continuous replication).
- Litestream's supported replica backends, current docs (SOURCED,
  `https://litestream.io/reference/config/`): `s3`, `gs` (GCS), `abs` (Azure Blob), `sftp`,
  `nats`, `oss` (Alibaba), `file` (local), `webdav`. **No native Google Drive backend.** Spec's
  premise ("Google Drive is not Google Cloud Storage") is confirmed correct.
- At current real size, `VACUUM INTO` + `zstd -19` produces a ~187 KB compressed snapshot
  (MEASURED, see Q2/Measurements). At an hourly cadence that is ≈4.5 MB/day (INFERRED:
  24 × 187 KB), far under B1's 150 MB/day egress budget — continuous replication buys essentially
  no practical RPO improvement worth a second moving part (an S3-compatible bucket, its own
  credentials, its own egress/cost) on top of Drive, and the workstream's own non-goals explicitly
  exclude "continuous sub-second replication."
- rclone (needed either way for the Drive leg) is confirmed to install and run natively in Termux
  ARM64 (MEASURED, see Q3) — the snapshot+rclone path needs no proot at all, fully satisfying D5;
  Litestream's chosen path cannot.

Runner-up: **(b) Litestream → S3-compatible bucket, with Drive as a secondary mirror.** Flip
condition: RPO requirements tighten below the hourly cadence (near-real-time replication becomes
a real requirement), or an S3-compatible bucket/credentials are already provisioned elsewhere in
this project (checked: none referenced in `.env` or `SYSTEM_RECORD.md` — would be new setup cost).

Confidence: **High.**

---

## Q2 · Snapshot method

**Decision: keep `VACUUM INTO` (matches [DEFAULT] D1) at the current DB size, but flag a
size-based trigger to switch to the Python `sqlite3` `.backup()` API with chunked stepping
(`pages=N, sleep=s`) once `app.db` grows past roughly tens of MB.**

All numbers MEASURED on a copy of the real `app.db` (2,310,144 bytes), never against the live
file:

| Method | Time | Peak RSS | Output |
|---|---|---|---|
| `VACUUM INTO` | 0.0716 s | 17,812 KB | 2,306,048 bytes, `PRAGMA integrity_check` = ok, row counts match source exactly (`chat_messages` = 203 both sides) |
| `.backup()` API (pages=-1, single shot) | 0.0341 s | 17,120 KB | 2,310,144 bytes, byte-identical copy |
| filesystem copy (`shutil.copy2`) | 0.0217 s | 15,724 KB | 2,310,144 bytes |
| `sqlite3_rsync` | n/a | n/a | **not available** — no `sqlite3` CLI at all exists on this device (neither Termux nor the proot guest ship one; only the Python-bundled `libsqlite3` 3.53.2 library exists), so the newer `sqlite3_rsync` tool that ships with recent SQLite CLI builds is absent |

At real size, all three methods are fast enough (< 0.1 s) and light enough (< 18 MB RSS) that
none would meaningfully violate R2 on their own. Filesystem copy is fastest/lightest but is ruled
out on **correctness** grounds, not speed: in `delete`-journal mode a raw file copy started while
a write is mid-flight can capture a torn/inconsistent file, because it does not go through
SQLite's own transactional snapshot — `VACUUM INTO`/`.backup()` do (SOURCED: SQLite locking
model — a raw `cp` has no lock awareness at all).

**Locking behavior under a live writer — MEASURED, not inferred**, using a synthetic 127 MB
inflated copy of the real schema+data (padded with a `_filler` blob table purely to get a
wall-clock window long enough to observe; this synthetic-size test is clearly separate from the
real-size numbers above and is documented as such):

- `VACUUM INTO` alone on the 127 MB copy: 0.815–0.895 s (two runs).
- Concurrent writer test: a second process attempted `INSERT ... ; COMMIT` starting ~0.15 s into
  the `VACUUM INTO`. The writer's call **blocked for 0.747 s** (`WRITER_WAIT_S=0.746955
  STATUS=OK`) — almost exactly the remaining vacuum duration — then succeeded. This is direct
  proof that in `delete`-journal mode, `VACUUM INTO`'s read transaction blocks a concurrent
  writer's commit for the **entire duration of the vacuum.**
- Reverse ordering test: a writer opened `BEGIN IMMEDIATE` + insert (acquiring RESERVED) and held
  it open for 0.6 s; `VACUUM INTO` started 0.2 s later and acquired its SHARED read lock while the
  writer was still open. The writer's own `COMMIT` (attempted right after its 0.6 s hold ended)
  then waited another 0.542 s (`COMMIT_WAIT_S=0.541674 STATUS=OK`) for `VACUUM INTO` to release
  its SHARED lock before the writer could upgrade to EXCLUSIVE and finish. Confirms the blocking
  is symmetric and matches standard SQLite rollback-journal locking rules (SOURCED: a writer
  cannot upgrade RESERVED→EXCLUSIVE while any other connection holds SHARED).
- **This scales with DB size.** At 2.3 MB the block is tens of milliseconds; at 127 MB it is
  ~0.8–0.9 s. If `app.db` grows substantially, an all-or-nothing `VACUUM INTO` becomes a real R2
  risk. `.backup()` has no equivalent all-or-nothing constraint — its Python API natively supports
  `pages=N, sleep=s` stepping (SOURCED: Python `sqlite3` stdlib docs), releasing the read lock
  between chunks so a pending writer gets a window. `VACUUM INTO` has no such stepping mode.

**SIGKILL-mid-run test (primary candidate, `VACUUM INTO`), on the same 127 MB synthetic copy:**
a calibration run completed in 0.923 s; a second run was SIGKILLed at 0.323 s (~35% through,
process confirmed still alive at signal time). Result: the target file **existed** (43,413,504
bytes, a partial write) but **does not open as a valid SQLite database** —
`sqlite3.connect(..., mode=ro)` + a query raised `OperationalError: attempt to write a readonly
database` (SQLite needs to attempt recovery on an incompletely-written file, which read-only mode
disallows; opened writable it would attempt journal rollback/recovery and is not safely
promotable either way). The **source** database (the 127 MB copy being read from) passed
`PRAGMA integrity_check` = `ok` afterward — the kill never touched the source. This is exactly
the failure mode **[LOCKED] R3** anticipates, and confirms D1's own wording ("VACUUM INTO a *temp
file*") is the right shape: the vacuum's destination must always be treated as a non-final temp
name, fsync'd and verified (e.g., re-opened + integrity-checked) before being renamed into the
promotable/upload path — a killed run must never leave something that could be mistaken for a
good snapshot.

Runner-up: `.backup()` API with `pages=N, sleep=s` chunked stepping. Flip condition: `app.db`
crosses roughly 20–50 MB (a judgment call — INFERRED from the observed 0.8–0.9 s block at 127 MB
scaling down — not itself independently measured at intermediate sizes) or write frequency rises
enough that even a sub-second block starts colliding with ticks in practice.

Confidence: **High** for the real-size numbers and the locking/SIGKILL behavior (directly
measured, reproducible, reasoning chain stated). **Medium** for the specific size threshold at
which to switch methods (that number is a judgment call, not measured).

---

## Q3 · rclone on this device

**Decision: rclone runs natively in Termux (ARM64) — no proot required. Google Drive OAuth setup
is blocked on a human (documented, not faked).**

- MEASURED: `pkg install -y rclone age` succeeded in native Termux. `rclone version` →
  `rclone v1.75.0-termux`, `os/arch: arm64 (ARMv8 compatible)`, `go/linking: dynamic`,
  `go1.26.5`. Same binary is reachable from *inside* the proot Ubuntu guest too, because Termux's
  `$PREFIX` is bind-mounted into the container (MEASURED: `command -v rclone` inside
  `proot-distro login ubuntu` resolves to `/data/data/com.termux/files/usr/bin/rclone`) — one
  install serves both worlds, satisfying D5 without extra setup.
- RSS during a real copy operation (a 186 KB compressed test snapshot, copied to a throwaway
  local-type rclone remote so no OAuth/network was needed): peak RSS **24,428 KB** (MEASURED).
  Modest; no tuning needed at this data volume.
- Default `--drive-chunk-size` = **8 Mi** (8,388,608 bytes) — MEASURED directly from the installed
  binary's own backend option table (`rclone config providers`), not the docs. Since real
  snapshots here (hundreds of KB, low single-digit MB even uncompressed) are far smaller than one
  chunk, resumable/chunked upload logic never engages — no tuning needed unless `app.db` grows
  into the tens-of-MB range.
- Default `--drive-use-trash` = **true** (MEASURED, same source). This means a retention script's
  deletes of superseded snapshots would move them to Drive's Trash rather than freeing quota
  immediately (Drive auto-empties trash after ~30 days) and could make "what's actually live"
  confusing under casual inspection. Recommend the retention/cleanup step explicitly pass
  `--drive-use-trash=false` so superseded snapshots are actually gone, keeping R4's
  filename-based retention unambiguous.
- **Drive OAuth on a headless phone — genuinely blocked, not attempted as a workaround.**
  `rclone config`'s Drive setup requires either pasting a code from an interactive browser consent
  screen or a local-webserver OAuth redirect — both need a real human completing Google's consent
  UI. Confirmed nothing pre-exists to shortcut this: no `GOOGLE_*`/`DRIVE_*`/`RCLONE_*`/`*_CLIENT*`
  env vars in `/root/odysseus/.env` (MEASURED, grep for names only), no `~/.config/rclone/*.conf`
  anywhere (MEASURED, empty dir), no `token.json`/`credentials*.json` under `/root` (MEASURED,
  `find` returned nothing). **What unblocks it:** a human (a) creates/uses an OAuth client ID in
  Google Cloud Console (also a browser action) and (b) runs `rclone config` (or
  `rclone authorize` from a machine with a browser) once, completing the consent screen for the
  target personal Google account, then copies the resulting token onto the phone. Until that
  happens, nothing Drive-specific (real upload duration, real rate-limit behavior) can be
  measured — see Q4.

Confidence: **Medium** overall (mechanics fully measured); **Low** specifically for anything
Drive-OAuth-dependent, explicitly because a human step is missing, not because it was skipped.

---

## Q4 · Drive API behaviour

**Decision: a personal OAuth client (installed-app / device-code flow) is the right fit, not a
service account. Retention must be filename-based, not reliant on Drive's built-in version
history.**

- Rate limits (SOURCED, `https://developers.google.com/workspace/drive/api/guides/limits`):
  1,000,000 quota units/minute/project; 325,000 quota units/minute/user/project; exceeding these
  triggers a `403 User rate limit exceeded`, and "additional rate limit checks on the Drive
  backend might also generate a `429: Rate limit exceeded`." Upload/egress ceiling: 750 GB/day
  (stated for Workspace accounts on that page; widely corroborated as the general per-account
  daily upload ceiling across account types). At real snapshot sizes here (hundreds of KB/hour)
  this is irrelevant by several orders of magnitude — not a practical constraint.
- Service account vs. personal OAuth client (SOURCED — Google's own developer forum threads plus
  independent corroboration from `kopia`, `n8n`, and `openclaw`'s public issue trackers, all
  2026): **a service account has zero Drive storage quota of its own and cannot own files in a
  personal "My Drive."** It can only write into Shared Drives, which require Google Workspace —
  not available on a free/personal Gmail account — or via domain-wide delegation, which requires
  a Workspace admin and doesn't apply here. INFERRED: since nothing in this project suggests a
  Workspace account is in play (personal phone, no organization referenced anywhere in `.env` or
  `SYSTEM_RECORD.md`), a service account would hit `storageQuotaExceeded` immediately — a personal
  OAuth client is the only workable choice, which also matches rclone's default/expected Drive
  setup path.
- Drive's native version history (SOURCED, general documented Drive behavior): Drive auto-keeps
  prior revisions per file but silently purges old ones after 30 days / 100 versions unless each
  revision is manually pinned "keep forever" — this does not scale to an unattended hourly job.
  **R4's retention must be filename-based** (distinct dated snapshot filenames), not dependent on
  Drive's own revision history.

Runner-up: none meaningfully distinct for the service-account question — it is close to
categorically ruled out for a personal account, not a close call. For retention, the runner-up to
"filename-based" would be "rely on Drive revision history," which flips only if the account were
migrated to Google Workspace with Shared Drives and revisions were explicitly pinned — not the
current setup.

Confidence: **High** (multiple independently corroborating sources for the service-account
finding; the exact numeric rate-limit page didn't separately break out personal vs. Workspace
egress ceilings, which is the one soft spot, noted above).

---

## Q5 · Encryption

**Decision: `age`, encrypting to a pre-generated public key kept on the phone; the private
identity is generated once and escrowed off the phone (password manager entry and/or a printed
copy), never stored only on the device being backed up.**

All timings MEASURED against the real compressed snapshot (`zstd -19` output, 191,565–191,824
bytes depending on run):

| Tool | Encrypt | Decrypt | Round-trip verified |
|---|---|---|---|
| `age` 1.3.2 (Termux pkg, ARM64) | 0.0388 s | 0.0384 s | byte-identical |
| `gpg` 2.5.17 symmetric (`-c`, AES256-CFB) | 0.397 s | 0.0874 s | byte-identical |
| `rclone crypt` | not independently benchmarked — see reasoning below | | |

- Both `age` and `gpg` symmetric were installed and actually run on this device (MEASURED, ARM64
  builds work fine). `rclone crypt` was not separately timed: it wraps a remote (encrypting
  filenames+content on the fly during a sync), which is a different usage shape than "encrypt one
  already-composed snapshot file, then upload it" — running it here would mostly re-measure
  rclone's own copy overhead (already captured in Q3) rather than anything new about encryption
  cost. Its key-escrow story is reasoned about below (SOURCED from rclone's own documented crypt
  design) rather than benchmarked, given the time budget.
- **Key-escrow story, stated plainly (R6):**
  - `age`: encryption only needs the **public** key (an `age1...` string), which can live in the
    backup script/config on the phone with no exposure risk if the phone is lost. The **private**
    identity file (from `age-keygen`) must be generated once, then moved off the phone entirely —
    e.g., a password manager entry, a printed/laminated copy kept elsewhere, or a second
    age-encrypted copy held by a different party. A restorer needs only that identity file plus
    the downloaded encrypted snapshot: `age -d -i identity.txt -o out.zst.dec snapshot.zst.age`,
    then decompress. No phone, no proot, nothing else required. This asymmetric shape is the
    reason `age` is recommended over the two alternatives: the *secret* half of the key material
    never needs to exist on the device being protected against loss in the first place.
  - `gpg` symmetric: the same passphrase is needed both to encrypt (on the phone, unattended, via
    `--passphrase-fd`) and to decrypt (on the laptop). For the phone's cron job to run
    unattended, that passphrase (or a file holding it) must exist *on the phone* — worse for R6
    than `age`'s model unless the passphrase is also independently escrowed elsewhere, at which
    point it's operationally equivalent to `age` but slower and clunkier to script.
  - `rclone crypt`: the encryption password lives in rclone's own config file (SOURCED: rclone
    crypt design — AES-256-CTR with a config-derived key), which by default sits on the phone —
    same class of R6 problem as `gpg`'s passphrase, with no advantage demonstrated here.

Given the LOCKED-item flag above — the local `app.db` holds real IMAP/SMTP passwords and OAuth
tokens (`email_accounts`), not just customer PII — this decision treats the data as
account-credential-grade, which reinforces (does not weaken) the case for `age`'s asymmetric
model: the backup script only ever needs to hold something that is safe to lose.

Runner-up: `gpg` symmetric — would be preferred only if the operator specifically wants a single
memorized passphrase instead of managing an identity keyfile, accepting the ~10x higher (but
still trivial, 0.4 s) CPU cost and the passphrase-on-device-for-cron tradeoff. `rclone crypt` is
the weakest fit: its native use case is "encrypt while syncing a tree," not "encrypt one composed
file," and its key-escrow story is no better than `gpg`'s.

Confidence: **High** for the performance numbers. **Medium** for "recommend `age`" as the overall
answer — it is a defensible design choice given the measured facts, not a uniquely-forced
conclusion (a team could reasonably choose `gpg` and accept the passphrase-escrow discipline
instead).

---

## Q6 · Liveness mechanism

**Decision: a hosted dead-man's-switch (e.g. Healthchecks.io free tier), using three distinct
check IDs — one each for scheduler-tick, backup-success, and device-online — to satisfy L1's
three-way distinction.**

- (a) **Hosted dead-man's-switch.** SOURCED, `https://healthchecks.io/pricing/`: the free
  "Hobbyist" tier is explicitly "Monitor 20 jobs" / "100 log entries per job" (a third-party 2026
  blog separately claimed "3 months of log history," which is not what the vendor's own pricing
  page states — noted as a discrepancy, official page treated as authoritative). Three checks
  easily fits inside 20. Scoring: **L1** — satisfied directly by using 3 separate check URLs, each
  pinged by a different phone-side signal (scheduler tick → check #1; backup script success →
  check #2; a periodic "device is up at all" ping, piggybacked on the existing `*/15 * * * *
  ensure_supervisor.sh` cron line already in the live crontab — MEASURED, `crontab -l` → exactly
  that one line today — → check #3); a missed grace window on any one fires its own distinct
  alert. **L2** — fully satisfied, entirely hosted, independent of phone and laptop. **B1
  bytes/wakeups** — three tiny HTTPS pings; at a 15-minute device-online cadence that's 96
  pings/day for that one signal alone, which is within B1's <100/day *only if* nothing else in
  this workstream also claims wakeup budget — this needs to be checked against the actual chosen
  scheduler-tick cadence in a later stage, not assumed here. **Alert latency** — as fast as the
  configured grace period (minutes). **Setup cost** — lowest of the four: a few `curl` calls added
  at existing hook points, no new server. **Third-party exposure** — the service sees only "did an
  opaque per-check URL get pinged on schedule," no data content. **Failure of the mechanism
  itself** — if the hosted service itself is down, missed-ping alerts silently don't fire;
  mitigated only by accepting this as a standard SaaS-dependency risk (the same class of risk
  already accepted by trusting Drive itself).
- (b) **Google Apps Script trigger reading a heartbeat file's `modifiedTime` in Drive.** SOURCED:
  this project already uses Apps Script for an analogous Drive-triggered pattern elsewhere
  (`research/odysseus-daily-driver/05-ops-module-research.md`, line 172: "the Apps Script `doPost`
  in `apps-script/queue-sync/`") — the pattern is proven feasible in this ecosystem, not
  theoretical. SOURCED trigger limits (`developers.google.com/apps-script/guides/services/quotas`
  and corroborating sources): `everyMinutes()` accepts only 1, 5, 10, 15, or 30; **max 20
  time-driven triggers per script**; **consumer (non-Workspace) accounts get only 90 minutes of
  total trigger runtime per day** (Workspace: 6 hours) — INFERRED this phone/account is a
  consumer account (no Workspace org referenced anywhere), so the 90 min/day ceiling applies, but
  a single lightweight per-minute heartbeat check is trivially small per execution and would not
  approach that ceiling on its own. Scoring: **L2** satisfied (runs on Google's infrastructure).
  **L1** is *harder* here — a single Drive `modifiedTime` check only tells you "the heartbeat file
  is stale," not which of scheduler/backup/device died, unless the phone writes a small JSON
  heartbeat with three separate timestamp fields that the script parses — doable, but pushes more
  complexity onto the phone side (another thing to upload regularly, competing for B1 budget) than
  option (a) does. **Setup cost** — medium (a new Apps Script project + a Drive API scope grant,
  i.e. another OAuth consent screen). **Third-party exposure** — none beyond what Drive already
  holds. **Failure of the mechanism itself** — silent trigger failures surface only in the Apps
  Script dashboard, less discoverable than a purpose-built monitoring UI.
- (c) **Laptop checks when awake.** Ruled out categorically — it structurally cannot satisfy
  **[LOCKED] L2** ("not dependent on the laptop being awake"). Not scored further.
- (d) **Self-hosted.** Would satisfy L1/L2 in principle but is the highest setup cost (new
  infrastructure that itself needs to stay alive and be monitored), which runs against this
  workstream's D6 spirit ("no new daemon, no new service manager") even though D6 is written about
  the phone side specifically.

Runner-up: (b) Apps Script. Flip condition: the team wants to avoid any third-party monitoring
SaaS entirely and is willing to accept coarser day-to-day visibility and the extra phone-side
complexity of a multi-field heartbeat file.

Confidence: **Medium** — the core comparison is SOURCED and internally consistent, but the actual
scheduler-tick cadence (needed to check the B1 wakeup-budget arithmetic precisely) was not
inspected this pass (out of scope: no scheduler internals code was read), so the specific "96
pings/day fits under 100" claim should be re-checked once the tick cadence is known.

---

## Q7 · Doze and the network

**Decision: cannot be fully measured this pass. What was measured points toward "probably already
survives," but the actual Doze/App-Standby behavior during a real unattended upload was not, and
could not responsibly be, observed in a single research session.**

- Why a direct measurement is genuinely impossible here: confirming real Doze-survival requires
  leaving the device idle and screen-off for an extended period with a real cron-triggered network
  job in place and then checking whether it ran — that is exactly the kind of multi-hour
  unattended observation this stage's constraints don't permit (no new persistent automation as a
  side effect of research, and a single research pass has no multi-hour idle window to honestly
  wait through). This is stated here rather than estimating a plausible-sounding number.
- What *was* measured: `dumpsys` (needed to query the Android battery-optimization/Doze whitelist
  directly) is **not invokable from Termux at all** — `dumpsys: command not found` (MEASURED;
  Termux's unprivileged shell has no `dumpsys` client; it needs `adb shell` or root, neither
  available here). `termux-api` package (0.59.1) is installed and the `termux-wake-lock` /
  `termux-battery-status` binaries exist (MEASURED), but invoking `termux-battery-status`
  non-interactively over SSH returned **no output at all** before an 8-second timeout (MEASURED) —
  the Termux:API companion Android app is either not installed/paired or not responding to the
  IPC broadcast in this session, so it cannot be relied on programmatically as-is; this needs a
  human with the physical device to check/pair the companion app before `termux-wake-lock` can be
  scripted with confidence.
- Indirect (INFERRED) evidence the device is already lenient toward background Termux: system
  uptime is **51 days, 3h10m** (MEASURED, `uptime`); the `crond` process has been running for
  ~137,042 s (~38 h) without being killed/restarted (MEASURED, `ps -o pid,etimes,comm`); other
  long-lived processes (`uvicorn`, the five MCP servers, the two `proot` guests, `dashboard.py`
  with ~25m45s of accumulated CPU time) show the same pattern. This is consistent with — but does
  not prove — Termux already being exempted from Android's battery-optimization/Doze whitelist (a
  common one-time manual setup step), which would be the necessary precondition for a
  cron-triggered upload to survive Doze.
- Recommendation regardless of the open question: hold `termux-wake-lock` for the duration of each
  upload as cheap insurance (SOURCED: this is the standard, well-documented Termux mitigation for
  exactly this class of problem) — its cost against B1 is not itself measured here (that requires
  the same unattended, multi-hour observation this pass couldn't do) but is generally understood
  to be small relative to holding a full CPU wakelock continuously. A real S4-time drill should
  include leaving the phone idle overnight with the actual backup cron installed, specifically to
  close this question with real data.

Runner-up / what would flip this: nothing to flip between options — this is a single question
without an alternative, and the only way to resolve it properly is the overnight drill described
above.

Confidence: **Low** for the actual Doze-survival claim — explicitly because `dumpsys` is
inaccessible, `termux-battery-status` was non-responsive, and no multi-hour unattended observation
was performed. **Medium** for "the wake-lock binary exists and is invokable" (that part is
directly measured) and for the inference that this specific device already tolerates long-lived
background processes.

---

## Q8 · What else is irreplaceable

All sizes MEASURED via `du -sh` against the live data directory (read-only).

| Item | Size | Decision | Reason |
|---|---|---|---|
| `app.db` | 2.3 MB | **Back up** | The core subject of this workstream. |
| Chroma persistent store (`chroma.sqlite3` + per-collection `header.bin`/`data_level0.bin`/`length.bin`/`link_lists.bin`/`index_metadata.pickle`) | 3.8 MB | **Back up** | Only `chroma.sqlite3` is a SQLite file — the HNSW index binaries are not, so `VACUUM INTO`/`.backup()` only cover part of it. Recommend a plain filesystem copy of the whole `chroma/` directory (small enough — 3.8 MB — that copy time is sub-second); flag for a later stage that stricter consistency may need Chroma quiesced first or its own export tooling, not assumed safe by default. |
| `.app_key` | 44 bytes | **Back up** | A generated crypto key, not derivable from `.env` or git (MEASURED: not referenced by name anywhere in `.env`). Something in Odysseus depends on it (likely session/field-level encryption); losing it without a backup makes anything it protects unreadable even after `app.db` is restored. Escrow alongside the R6 backup-encryption key material. |
| `auth.json` (bcrypt admin hash) | 151 bytes | **Re-derivable, excluded** | A documented runbook (`SYSTEM_RECORD.md`, "Resetting the Odysseus admin password") regenerates it via `setup.py`; that runbook is already versioned in this git repo, so as long as the repo survives, so does the recovery path. |
| `/root/odysseus/.env` (guest) | 165 lines, incl. live Supabase service-role key | **Back up (encrypted)** | Gitignored secrets, not reconstructible from git; losing it loses live Supabase/integration access even after `app.db` is restored. |
| `email_accounts` row data (IMAP/SMTP passwords, OAuth tokens) | inside `app.db` | **Covered by `app.db` backup** | Flagged separately because it's the single most sensitive payload in the system — see the LOCKED-item flag above; this is what drove the Q5 encryption decision. |
| crontab (`*/15 * * * * ensure_supervisor.sh`) | 1 line | **Re-derivable, excluded** | The one active line and the script it calls are already versioned in this repo (`phone/`, `SYSTEM_RECORD.md`). |
| Tailscale node state | n/a | **Excluded, out of Termux's reach** | Tailscale runs as a separate Android VPN app; MEASURED: no `tailscale` binary anywhere in Termux (`command not found`). If the phone is lost, the node is simply removed from the tailnet admin console and a replacement device re-authenticates — fully re-derivable via the account, not a local secret. |
| Scheduler state (`scheduled_tasks` 11 rows, `task_runs` 212 rows) | inside `app.db` | **Covered by `app.db` backup** | No separate scheduler state file exists outside the db (MEASURED: only these two tables hold this data). |
| `fastembed_cache` | 217 MB | **Re-derivable, excluded** | A downloaded ONNX embedding model artifact (confirmed by `SYSTEM_RECORD.md` Rev D's account of repairing exactly this cache from scratch); excluding it keeps the backup small and well under B1's egress budget. Re-fetched on restore via the existing `odysseus_fetch_embeddings.py`. |
| `logs/`, `tts_cache/`, `emoji_cache/`, `email_urgency_cache/`, `cache/` | 5.4 MB, <1 MB each | **Excluded** | Ephemeral/regenerating caches and logs; no restore-blocking value. |
| `deep_research/`, `projects/`, `bilweekend/`, `hwfit/`, `skills/`, `personal_docs/`, `personal_uploads/`, `mail-attachments/`, `generated_images/`, `uploads/` | 52 KB–900 KB each today | **Back up (secondary, lower-frequency archive)** | User-generated flat files referenced by rows in `documents`/`gallery_images`/`project_links`, living outside `app.db`. Currently small, but a db-only backup would silently lose anything a restored row points to on disk. **This is a real gap in D1 as currently scoped** (D1 only names the database) — reported as a finding, not silently absorbed: recommend a daily (not hourly) filesystem archive of the data dir minus the excluded caches above. |
| Bil Weekend customer/booking PII (`bookings`, `contacts`, `curated_requests`, `queue_requests`, `operators`) | n/a (Supabase-hosted) | **Excluded by design** | Confirmed live (MEASURED: absent from `app.db`'s table list) and SOURCED (`SYSTEM_RECORD.md` Rev S): fetched live from a separate Supabase project via PostgREST, never stored on the phone. The spec's own non-goals also exclude "anything touching the ops schema." This is the resolution referenced in the LOCKED-item flag above. |

Confidence: **High** — every row above is either a direct filesystem/db measurement or a citation
to an existing, already-versioned document in this repo; the one judgment call (whether the
low-frequency flat-file archive is "in scope" for this workstream) is flagged explicitly as a gap
rather than silently decided.

---

## Measurements appendix

All commands were run over SSH to the phone (`ssh_termux.py`, connection constants from
`phone_connection.py`) or via `push_and_run.py` (native Termux, no `--proot`, per D5). Nothing
destructive ran against the live `app.db`; every snapshot/kill/concurrency test ran against a copy
under `/data/data/com.termux/files/home/ws01_scratch/`, created via `cp -p` from the live file
before any test began.

### Live-system identification

```
$ proot-distro login ubuntu -- bash -lc 'grep -E "ODYSSEUS_DATA_DIR|GOOGLE_OAUTH|SUPABASE" /root/odysseus/.env | sed -E "s/=.*(KEY|TOKEN|SECRET|PASSWORD).*/=<redacted>/"'
ODYSSEUS_DATA_DIR=/data/data/com.termux/files/home/odysseus-data
SUPABASE_URL=https://hjjkmknqunwlhrfulrdl.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<redacted>

$ ls -la /data/data/com.termux/files/home/odysseus-data/app.db /root(rootfs)/odysseus/data/app.db
-rw-------. 1 u0_a349 u0_a349 2310144 Sep  1 12:50 .../odysseus-data/app.db   (live)
-rw-r--r--+ 1 root    root     757760 Sep  1 09:53 .../rootfs/root/odysseus/data/app.db  (stale fallback)

$ date
Tue Sep  1 12:53:50 +03 2026

$ ps -ef | grep -E 'uvicorn|python|crond|proot'
u0_a349  1408 ...  proot ... /root/run-odysseus.sh
u0_a349  1416 1413 ... chroma run --host 127.0.0.1 --port 8100 --path .../odysseus-data/chroma
u0_a349  1561 1413 ... python3 -m uvicorn app:app --host 0.0.0.0 --port 7000
u0_a349  1876/1888/1891/1914/1915  1561 ...  mcp_servers/{image_gen,memory,rag,email,ops}_server.py
u0_a349 14536    1 ... crond
```

### Journal mode / busy_timeout / schema / row counts (read-only PRAGMA + SELECT, live file)

```
$ python3 -c "
import sqlite3
con = sqlite3.connect('file:/data/data/com.termux/files/home/odysseus-data/app.db?mode=ro', uri=True)
cur = con.cursor()
cur.execute('PRAGMA journal_mode'); print(cur.fetchall())
cur.execute('PRAGMA busy_timeout'); print(cur.fetchall())
cur.execute('SELECT name FROM sqlite_master WHERE type=\"table\" ORDER BY name')
print([r[0] for r in cur.fetchall()])
"
journal_mode [('delete',)]
busy_timeout [(5000,)]
tables ['api_tokens', 'caldav_deleted_events', 'calendar_events', 'calendars', 'chat_messages',
'chat_messages_fts', 'chat_messages_fts_config', 'chat_messages_fts_content',
'chat_messages_fts_docsize', 'chat_messages_fts_idx', 'comparisons', 'crew_members',
'document_versions', 'documents', 'editor_drafts', 'email_account_owner_locks', 'email_accounts',
'gallery_albums', 'gallery_images', 'integrations', 'mcp_servers', 'memories', 'model_endpoints',
'notes', 'operations_agent_queue', 'operations_notes', 'operations_staged_changes',
'project_links', 'project_tasks', 'projects', 'provider_auth_sessions', 'scheduled_tasks',
'sessions', 'signatures', 'task_runs', 'user_tool_data', 'user_tools', 'webhooks']
```

Row counts (read-only, structure/counts only, no content dumped):

```
api_tokens 1, caldav_deleted_events 0, calendar_events 13, calendars 2, chat_messages 203,
comparisons 0, crew_members 1, document_versions 14, documents 5,
editor_drafts 0, email_account_owner_locks 0, email_accounts 4, gallery_albums 0,
gallery_images 0, integrations 0, mcp_servers 0, memories 0, model_endpoints 3, notes 1,
operations_agent_queue 0, operations_notes 1, operations_staged_changes 0, project_links 0,
project_tasks 63, projects 21, provider_auth_sessions 0, scheduled_tasks 11, sessions 35,
signatures 0, task_runs 212, user_tool_data 0, user_tools 0, webhooks 0
```

Columns for credential-shaped tables (names only, no data):

```
email_accounts :: ['id','owner','name','is_default','enabled','imap_host','imap_port','imap_user',
'imap_password','imap_starttls','smtp_host','smtp_port','smtp_security','smtp_user',
'smtp_password','from_address','display_name','oauth_provider','oauth_access_token',
'oauth_refresh_token','oauth_token_expiry','created_at','updated_at']
provider_auth_sessions :: ['id','provider','owner','label','base_url','access_token',
'refresh_token','last_refresh','auth_mode','created_at','updated_at']
```

### Sizes

```
$ du -sh /data/data/com.termux/files/home/odysseus-data/
232M

$ du -sh chroma fastembed_cache logs bilweekend hwfit deep_research projects skills cache \
   mail-attachments personal_docs personal_uploads generated_images tts_cache emoji_cache \
   email_urgency_cache memory_vectors uploads rag
3.8M  chroma
217M  fastembed_cache
5.4M  logs
218K  bilweekend
900K  hwfit
52K   deep_research
382K  projects
34K   skills
867K  cache
7.0K  mail-attachments
7.0K  personal_docs
3.5K  personal_uploads / generated_images / tts_cache / memory_vectors / uploads / rag (each)
108K  emoji_cache
56K   email_urgency_cache

$ find odysseus-data/chroma -maxdepth 2
chroma/chroma.sqlite3
chroma/<uuid>/{header.bin,data_level0.bin,length.bin,link_lists.bin}
chroma/<uuid>/{...,index_metadata.pickle}
```

### System facts

```
$ free -h
Mem:  total 10Gi  used 6.7-6.8Gi  free ~1Gi  available 3.6Gi
Swap: total 11Gi  used 2.4Gi

$ uname -m / uname -a
aarch64 / Linux localhost 6.1.145-android14-11-33419968-abS928BXXS6DZE1 ... Android

$ uptime
13:08:04 up 51 days, 3:10, load average: 2.83, 2.69, 2.76

$ ps -o pid,etimes,comm -p 14536
14536  137042  crond

$ crontab -l
*/15 * * * * /data/data/com.termux/files/home/ensure_supervisor.sh

$ dumpsys deviceidle whitelist
bash: dumpsys: command not found

$ timeout 8 termux-battery-status
(no output before timeout — Termux:API companion app not responding)

$ command -v tailscale
(not found — Tailscale runs as a separate Android app, not via Termux)
```

### Tool installs (left on device — documented per the hard constraints, not reverted)

```
$ pkg install -y rclone age
Installed: age 1:1.3.2, rclone 1.75.0   (both aarch64, native Termux packages)

$ proot-distro login ubuntu -- bash -lc 'dpkg -i /root/litestream_test.deb; litestream version'
Installed litestream 0.3.13 inside the proot Ubuntu guest (glibc). Left installed.

$ rclone version
rclone v1.75.0-termux, os/arch: arm64 (ARMv8 compatible), go/version: go1.26.5, go/linking: dynamic

$ gpg --version | head -1
gpg (GnuPG) 2.5.17           # pre-existing on device before this session
$ zstd --version / xz --version
Zstandard CLI v1.5.7 / xz (XZ Utils) 5.8.3   # both pre-existing
```

Side effects left on the device, documented per the hard constraints (nothing uninstalled, nothing
undone):
- `rclone` and `age` now `pkg`-installed in native Termux (used by future stages if D1 is
  implemented).
- `litestream` `dpkg`-installed inside the proot Ubuntu guest, purely to prove Q1's
  installability/compatibility finding above. Not wired into anything, not started as a service.
- A throwaway `age` keypair, a throwaway `rclone` config pointing at a local test remote, and
  test snapshot/compressed/encrypted artifacts remain under
  `/data/data/com.termux/files/home/ws01_scratch/` (~53 MB after cleanup of the larger synthetic
  test files). None of it touches the default rclone config path (`~/.config/rclone/` remains
  empty of any `.conf` file) or any production path.
- `~/.gnupg/pubring.kbx` (32 bytes, empty keybox) was recreated by the `gpg` symmetric-encryption
  test, since even symmetric-only `gpg` operations require a GnuPG homedir. No keys were added to
  it. `~/.gnupg/private-keys-v1.d` and the agent sockets pre-date this session (dated Jun 17 / Aug
  30) and were not touched.
- No crontab, `Start_All.sh`/`Stop_All.sh`/`supervise_services.sh`, systemd/service file, or OAuth
  token was created, changed, or saved as production credential material.

### Snapshot-method timings (real size, JSON excerpt from the actual run)

```
"vacuum_into_real": {"stdout": "TIME_S=0.071639\nRSS_KB=17812"}, out size 2306048
"backup_api_real":  {"stdout": "TIME_S=0.034071\nRSS_KB=17120"}, out size 2310144
"fscopy_real":      {"stdout": "TIME_S=0.021653\nRSS_KB=15724"}, out size 2310144
"sqlite3_rsync_available": false
```

### Concurrency / SIGKILL tests (synthetic 127 MB copy, clearly separate from real-size numbers)

```
"inflated_db_size_bytes": 127160320
"concurrency_test_v2": {
  "vac_stdout": "VACUUM_TIME_S=0.894703",
  "writer_stdout": "WRITER_WAIT_S=0.746955 STATUS=OK"
}
"writer_holds_txn_then_vacuum_starts": {
  "writer_stdout": "COMMIT_WAIT_S=0.541674 STATUS=OK",
  "vacuum_stdout": "VACUUM2_TIME_S=0.842549 STATUS=OK"
}
"sigkill_test": {
  "full_run_duration_s": 0.9231537505984306,
  "kill_delay_s": 0.3231038127094507,
  "was_alive_when_signal_sent": true,
  "target_file_exists_after_kill": true,
  "target_file_size_after_kill": 43413504,
  "target_opens_as_sqlite": false,
  "target_integrity_check": "OperationalError('attempt to write a readonly database')",
  "source_integrity_check_after_kill": [["ok"]]
}
```

### Compression (on the real-size `VACUUM INTO` output, 2,306,048 bytes)

```
zstd -19: 0.390 s -> 191,333 bytes (8.30%)
zstd -3 : 0.035 s -> 221,941 bytes (9.62%)
gzip -9 : 0.134 s -> 320,216 bytes
xz -6   : 0.388 s -> 177,656 bytes (smallest)
```

### Encryption (on the zstd -19 output, ~191 KB)

```
age encrypt: 0.0388 s -> 191,565 bytes ; age decrypt: 0.0384 s ; round-trip byte-identical
gpg -c (AES256-CFB) encrypt: 0.397 s -> 191,824 bytes ; decrypt: 0.0874 s ; round-trip byte-identical
```

### rclone

```
$ rclone config providers | python3 -c "... extract drive backend option defaults ..."
chunk_size 8388608
use_trash True

$ rclone --config <scratch>.conf copyto <191KB file> localtest:<dir>/snap.bin -v
Transferred: 186.849 KiB / 186.849 KiB, 100%
RSS_KB=24428
```

### Litestream

```
$ proot-distro login ubuntu -- bash -lc 'dpkg -i litestream_0.3.13_arm64.deb; litestream version'
v0.3.13   (installs and runs fine inside the proot glibc guest)

$ /data/data/com.termux/files/home/ws01_scratch/litestream_bin version   # same binary, native Termux
Unknown signal 31   (crashes outside proot / glibc environment)
```

---

## Contradictions and surprises

- **The R5 contradiction is the headline finding** — flagged at the top of this file per protocol,
  not repeated in full here. In short: the literal "Bil Weekend worklist in the database" claim
  is false today (that data is Supabase-hosted, fetched live), but the database turned out to hold
  something arguably more sensitive (plaintext IMAP/SMTP passwords and OAuth tokens in
  `email_accounts`), so R5's encryption requirement is upheld and arguably strengthened rather
  than dismissed.
- **`VACUUM INTO` blocking a concurrent writer for its full duration, in proportion to DB size, was
  directly measured and is a real finding**, not something assumed from documentation: 0.75 s of
  writer stall at 127 MB, confirmed symmetric in both call orders. At the database's actual
  current size (2.3 MB) this is a non-issue (tens of ms), but it means D1's "VACUUM INTO, hourly"
  default has a size ceiling before it needs to change to a chunked `.backup()` approach — this
  wasn't obvious from the spec's framing of Q2 as a menu of options with no stated preference.
- **Litestream cannot run in native Termux at all** (`Unknown signal 31` on the glibc binary) —
  this was a genuine surprise going in, since D5's ptrace-overhead concern was framed as a
  performance tradeoff to weigh, not a hard "can't run there at all" wall. It turned out to be the
  latter, which makes the Q1 decision (reject Litestream) more clear-cut than a pure cost/benefit
  analysis would have suggested.
- **D1 as currently scoped only backs up the database, but real user-referenced files
  (`documents`, `gallery_images`, `project_links` rows pointing at flat files under
  `personal_docs/`, `generated_images/`, etc.) live outside `app.db` entirely.** This is reported
  under Q8 as a scope gap, not silently patched into D1 — a restore that follows D1 literally would
  bring back rows that reference files nobody backed up.
- One thing checked and confirmed as expected, with nothing surprising: the snapshot methods
  (`VACUUM INTO`, `.backup()`) both produced outputs that passed `PRAGMA integrity_check = ok`
  and matched the source's `chat_messages` row count (203) exactly, at real size — i.e., the
  "boring" case (a clean, non-interrupted snapshot) behaves exactly as SQLite's documentation says
  it should, on this device, at this size. No surprises there — worth stating so the successful
  case isn't left unverified next to the more interesting failure-mode findings above.
