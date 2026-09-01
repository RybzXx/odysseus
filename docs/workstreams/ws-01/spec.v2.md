# ws-01 — Phone Database Recoverability & Liveness (spec v2)

Supersedes `spec.md`. Everything not listed in the changelog is unchanged from v1.

## Changelog vs spec.md

- **R5 resolved** — Path B chosen: no client-side encryption; Google Drive is accepted as the
  trust boundary. Resolution and reasoning recorded under R5 below, as R5 itself requires.
  Origin: user decision (this session), after S1 research (`research.md` Q5) had recommended
  encryption via `age` — that recommendation is not adopted.
- **R6 status noted** — not currently triggered, since no encryption is in use. Text unchanged
  (it is [LOCKED]); a status note is appended below it.
- **[DEFAULT] D1 changed**: dropped the "encrypt" step. Was "`VACUUM INTO` a temp file, compress,
  encrypt, upload with rclone." Now "`VACUUM INTO` a temp file, compress, upload with rclone."
  Reason: direct consequence of the R5 resolution above. Origin: user decision.
- **[DEFAULT] D7 added** (new): daily flat-file archive of user-referenced directories, alongside
  the hourly DB snapshot. Reason: S1 (`research.md` Q8) found that `documents`/`gallery_images`/
  `project_links` rows reference files living outside `app.db`; a DB-only backup leaves restored
  rows pointing at files that were never saved. Origin: research finding (S1) + user decision
  (chose "DB + daily archive" over "DB-only" at the design stage).
- **[DEFAULT] D8 added** (new): liveness mechanism is a Google Apps Script trigger reading a
  three-field heartbeat file's state in Drive (scheduler-tick / backup-success / device-online),
  not a hosted third-party dead-man's-switch. Origin: user decision, selected over S1's
  Medium-confidence recommendation (Healthchecks.io) at the design stage. No additional reasoning
  was stated for the override beyond the choice itself — recorded as a decision, not backfilled
  with an invented justification.
- Q1–Q6 and Q8 marked resolved below, pointing at `research.md` for the underlying evidence
  rather than duplicating it. Q7 remains open.
- One new open item added: verify no third-party app holds Drive OAuth scope on the backup
  Google account (see Open questions).

---

## Problem

*(unchanged from spec.md — see there for the full Problem / Definition of done sections)*

## Invariants

*(all [LOCKED] items are unchanged verbatim from spec.md; only R5 and R6 carry an added
resolution/status note below their original text, per protocol — the original wording is not
altered)*

- **[LOCKED] R5.** The database contains customer PII (names, emails, phone numbers, request text
  from the Bil Weekend worklist). Either it is encrypted client-side before it leaves the device,
  or the decision to treat Google Drive as an acceptable trust boundary is recorded explicitly in
  spec.v2.md with the reasoning. Silence is not an option here.

  > **Resolution (this document): Path B — Google Drive is accepted as the trust boundary. No
  > client-side encryption is used.**
  >
  > Reasoning, as stated by the account owner (user input, not inferred):
  > - Sole owner of the backing Google account; no shared or delegated access.
  > - Two-factor authentication is enabled on that account.
  >
  > Not yet confirmed — open item, not assumed either way: whether any third-party application
  > currently holds an OAuth grant with Drive scope on this account. This should be checked
  > (`myaccount.google.com/permissions`) before this resolution is treated as fully closed; see
  > Open questions.
  >
  > Also noted for the record (S1 finding, `research.md`): R5's literal premise — that Bil Weekend
  > customer PII sits in this database — is false as of the S1 research date; that data is
  > Supabase-hosted and fetched live. What the database actually contains, and what this
  > resolution therefore leaves unencrypted in Drive, is the `email_accounts` table's real IMAP/
  > SMTP passwords and OAuth tokens, plus `chat_messages`, `notes`, `documents`, and other
  > account content. The trust-boundary decision above is made with that in view, not with the
  > spec's original (now-superseded) description of what's at risk.

- **[LOCKED] R6.** If encryption is used, the decryption key must be recoverable without the
  phone. A key that exists only on the device being backed up protects nothing.

  > **Status: not currently triggered.** No encryption is in use (see R5 resolution above), so
  > there is no key to escrow. This item becomes binding again if encryption is ever
  > (re)introduced for this workstream.

*(R1–R4, L1–L2, B1 unchanged — see spec.md)*

## Defaults

- **[DEFAULT] D1** (amended): `VACUUM INTO` a temp file, compress, upload with rclone to a Drive
  remote. Hourly. *(Encryption step removed — see Changelog and R5 resolution above.)*
- [DEFAULT] D2–D6: unchanged — see spec.md.
- **[DEFAULT] D7** (new): Daily (not hourly) filesystem archive of user-referenced flat-file
  directories under the data dir (`documents`-linked, `gallery_images`-linked, `project_links`-
  linked paths — concretely `personal_docs/`, `personal_uploads/`, `generated_images/`,
  `mail-attachments/`, `uploads/`, and similar small content directories), excluding regenerable
  caches (`fastembed_cache/`, `logs/`, `tts_cache/`, `emoji_cache/`, `email_urgency_cache/`,
  `cache/`) per S1's Q8 findings. Runs alongside D1, not instead of it.
- **[DEFAULT] D8** (new): Liveness checker is a time-driven Google Apps Script trigger reading a
  heartbeat file in Drive. The heartbeat file carries three independent timestamp fields —
  scheduler-tick, backup-success, device-online — so one script can still satisfy L1's three-way
  distinction despite reading a single file. (Design detail — the three-field shape — carried
  over from S1's Q6 analysis of this option; not yet built.)

## Open questions

Status after S1 (`research.md`) and the design-stage decisions above:

- **Q1 Transport** — Resolved: snapshot + rclone to Drive (unchanged from D1's shape). See
  `research.md` Q1.
- **Q2 Snapshot method** — Resolved: `VACUUM INTO` for now; switch to chunked `.backup()` once
  `app.db` crosses roughly tens of MB (exact threshold is a judgment call, Medium confidence).
  See `research.md` Q2.
- **Q3 rclone** — Resolved: runs natively in Termux, no proot needed. Google Drive OAuth setup is
  still blocked on a human completing the consent flow once — unchanged, still needs doing before
  D1/D8 can be built end-to-end. See `research.md` Q3.
- **Q4 Drive API** — Resolved: personal OAuth client, filename-based retention. See `research.md`
  Q4.
- **Q5 Encryption** — Superseded by the R5 resolution above (no encryption used). S1's own
  Medium-confidence recommendation (`age`) is not adopted; see Changelog.
- **Q6 Liveness** — Resolved via D8 above (Apps Script + Drive heartbeat), overriding S1's
  Medium-confidence recommendation (Healthchecks.io). See `research.md` Q6 for the full tradeoff
  table this choice was made from.
- **[OPEN] Q7 Doze and the network** — Still open. S1 could not measure this (Low confidence,
  `research.md` Q7) — genuinely requires an unattended overnight drill with the real backup cron
  installed. Deferred to S4.
- **Q8 What else is irreplaceable** — Resolved: see D7 above and `research.md` Q8 for the full
  back-up/re-derivable/excluded table.
- **[OPEN] New — Drive account third-party access.** Confirm whether any third-party app holds an
  OAuth grant with Drive scope on the backup Google account. Blocks treating the R5 resolution as
  fully closed. Owner: account holder (human-only check).

## Non-goals

*(unchanged from spec.md)*
