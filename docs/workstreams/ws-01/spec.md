# ws-01 — Phone Database Recoverability &amp; Liveness

## Problem

The primary SQLite database lives on an unrooted Galaxy S24 Ultra running Termux + PRoot Ubuntu. It is the only copy. Android 15/16 kills long-running Termux processes, and a lost, reset, or bricked phone ends the system permanently. Separately, when the scheduler dies there is no signal — a six-hour gap in triage is indistinguishable from six quiet hours.

Two capabilities, one workstream because they share a heartbeat path:

- **R — Recoverability.** The database can be restored onto a different machine after total loss of the phone.
- **L — Liveness.** Something that is not the phone notices, within minutes, when the scheduler stops ticking or the backup stops arriving.

## Definition of done

Not "a backup exists." A restore drill succeeded: the newest backup was pulled onto the laptop by someone following only the written runbook, opened, passed `PRAGMA integrity_check`, and matched live row counts within the expected drift window. Until that has happened, this workstream is not done.

## Invariants

- **[LOCKED] R1.** Recovery is proven by a drill, not by the existence of a file. S4 performs a real restore on the laptop from the real Drive contents.
- **[LOCKED] R2.** The backup path must never block, slow, or crash a scheduler tick. Backup failure is a logged, alertable event — never an exception that propagates into the scheduler.
- **[LOCKED] R3.** No partial artifact is ever promoted. Write to a temp name, fsync, verify, then atomically rename/upload. Assume the process is SIGKILLed at the worst possible moment, because on this device it will be.
- **[LOCKED] R4.** Versioned retention. A scheme that overwrites a single copy is not a backup — it propagates corruption to the only good copy. Corruption discovered N days late must still be recoverable.
- **[LOCKED] R5.** The database contains customer PII (names, emails, phone numbers, request text from the Bil Weekend worklist). Either it is encrypted client-side before it leaves the device, or the decision to treat Google Drive as an acceptable trust boundary is recorded explicitly in spec.v2.md with the reasoning. Silence is not an option here.
- **[LOCKED] R6.** If encryption is used, the decryption key must be recoverable without the phone. A key that exists only on the device being backed up protects nothing.
- **[LOCKED] L1.** The liveness alert must reach a human who is not looking at the phone, and must distinguish at minimum: scheduler dead, backup failing, device offline. One undifferentiated "something is wrong" alarm gets ignored inside a week.
- **[LOCKED] L2.** The checker runs somewhere that is not the phone and not dependent on the laptop being awake.
- **[LOCKED] B1.** Resource budget, measured in S4 and reported as numbers:
  - added sustained CPU on the phone: < 1%
  - added battery drain: < 1.5% / day
  - added network egress: < 150 MB / day at current DB size
  - added wakeups attributable to this workstream: < 100 / day

  Exceeding a budget is not a failure to hide; it is a finding to report with the measurement.

## Defaults

Change these if research says so, but log it.

- **[DEFAULT] D1.** `VACUUM INTO` a temp file, compress, encrypt, upload with rclone to a Drive remote. Hourly.
- **[DEFAULT] D2.** Retention: 24 hourly, 14 daily, 6 monthly.
- **[DEFAULT] D3.** Wi-Fi only. Mobile data in Baghdad is metered and an hourly multi-MB upload on cellular is not acceptable. Queue and catch up on reconnect.
- **[DEFAULT] D4.** Heartbeat written by the scheduler to a heartbeat table every tick; a separate lightweight process is responsible for reporting it outward.
- **[DEFAULT] D5.** Run the backup job in native Termux rather than inside PRoot, if the tooling permits — PRoot's ptrace overhead lands hardest on exactly this kind of syscall-heavy I/O.
- **[DEFAULT] D6.** Everything is a shell script plus cron. No new daemon, no new service manager, no Python dependency that has to build on ARM64.

## Open questions

S1 must resolve every one of these.

- **[OPEN] Q1 · Transport.** Litestream is the obvious continuous-replication answer, but verify its supported backends for the current version. Google Drive is not Google Cloud Storage. If Drive is unsupported, is the right answer (a) snapshot + rclone to Drive, (b) Litestream to an S3-compatible bucket with Drive as a secondary mirror, or (c) something else? Decide on recovery-point objective, cost, and number of moving parts.
- **[OPEN] Q2 · Snapshot method.** `VACUUM INTO` vs the `.backup` API vs `sqlite3_rsync` vs filesystem copy of db+WAL. For each: what lock does it take against a live writer in WAL mode, for how long, how does it behave if killed mid-run, and what does it cost at this DB size? Test on a copy of the real database, not a toy one.
- **[OPEN] Q3 · rclone on this device.** Does it install and run in native Termux (ARM64), or must it live inside PRoot? How is the Drive OAuth flow completed on a headless phone? What is its resident memory footprint and default chunk size, and do those need tuning for a memory-constrained device? Does `--drive-use-trash` interfere with retention?
- **[OPEN] Q4 · Drive API behaviour.** Per-user rate limits and the 403 `rateLimitExceeded` path; whether a personal OAuth client or a service account is the better fit here; what happens to a service account's quota on a personal Drive; whether Drive's own version history can serve part of R4 or whether retention must be filename-based.
- **[OPEN] Q5 · Encryption.** Compare age, gpg symmetric, and an rclone crypt remote on: availability of a working ARM64 build in Termux, CPU cost per run at this DB size, and — most important — the key-escrow story that satisfies R6. State plainly where the key lives, who can reach it, and how a restore is performed by someone holding only the recovery material.
- **[OPEN] Q6 · Liveness mechanism.** Compare at least: (a) a hosted dead-man's-switch on a free tier, (b) a time-driven Google Apps Script trigger reading the heartbeat file's `modifiedTime` in Drive — note that Apps Script is already in use for the queue mirror, (c) the laptop checking when awake, (d) self-hosted. Score each against: satisfies L1's three-way distinction; satisfies L2; bytes and wakeups per day on the phone (B1); alert latency; setup cost; what a third party learns about the system; and what happens to the alert path when the mechanism itself fails. Recommend one, and say what would make you choose differently.
- **[OPEN] Q7 · Doze and the network.** Does a cron-triggered network upload actually complete when the device is in Doze / App Standby? Is `termux-wake-lock` required for the duration of the upload, and what does holding it cost against B1? What is the observed behaviour on One UI with Termux in the never-sleep list?
- **[OPEN] Q8 · What else is irreplaceable.** The DB is the obvious thing. Enumerate what else on the phone cannot be rebuilt from a git repo: Chroma's persistent store, credentials and tokens, crontab, `.env` files, the Tailscale node state, scheduler state. For each, decide: back up, re-derivable, or deliberately excluded. Excluded items get a one-line reason.

## Non-goals

Continuous sub-second replication. High availability. Restoring onto the phone itself (recovery target is the laptop or any Linux host). Backing up the 21 project repos — they are already in git. Anything touching the ops schema.
