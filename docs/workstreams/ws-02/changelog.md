# ws-02 changelog

## Decided

- Q1 (boundary placement): storage layer, not a decorator or the MCP boundary.
- Q1 refined to Option B: enforcement lives at the SQLAlchemy ORM level — a
  `load` event on `Base` with `propagate=True` — rather than new per-store
  helper functions (Option A). Chosen over A because it can't be bypassed by a
  future call site the helper-function approach would need to remember to use.
- No exemption list for models without an `integrity` column: I1 (fail closed)
  and I4 (no undeclared promotion to SYSTEM) together rule that out.
- No Supabase changes. `operations_notes` lives in local SQLite
  (`core/database.py`, `app.db`), not Supabase, so that constraint didn't
  bear on the A/B choice. The live `app.db` is on the phone; no migration is
  run from this worktree.

## Built

- `combine_result_integrity()`, `coerce_result_integrity()` — extend the
  existing `ResultIntegrity` enum (`src/tool_capabilities.py`) with an
  explicit max-combiner and a fail-closed coercion for unknown/missing values.
- `ToolRunSecurityContext.observe_data_integrity()` — shadow-mode only:
  updates a new `shadow_data_integrity` field and logs (integrity value,
  source_ref, row id, run id — no row content); never touches
  `external_untrusted_context_seen` or `decision_for()`.
- `ACTIVE_RUN_SECURITY` `ContextVar` (`src/tool_capabilities.py`) — exposes
  the active run's security context to code with no argument path to it,
  matching the existing `_active_workspace`/`_CURRENT_OWNER` ContextVar
  pattern already in this codebase.
- `_observe_row_integrity_shadow` — `@event.listens_for(Base, "load",
  propagate=True)` hook in `core/database.py`, next to the existing
  `set_sqlite_pragma` listener. Fires on every mapped model's row load;
  reads `ACTIVE_RUN_SECURITY`, no-ops if unset; wrapped in try/except so a
  hook failure cannot break a real read.
- `execute_tool_block` (`src/tool_execution.py`) sets/resets
  `ACTIVE_RUN_SECURITY` around each tool call, in the same try/finally as the
  pre-existing `_active_workspace` binding.
- Tests: `tests/test_tool_capabilities.py` (15 cases — combiner ordering,
  empty set, unknown/None fail-closed, shadow-only observation, monotonic
  combination, log content) and `tests/test_orm_integrity_shadow_hook.py`
  (3 cases, in-memory SQLite only — untagged row reads back untrusted, no-op
  with no active run, hook fires for `Note` as well as `OperationsNote`).

## Learned

- `ResultIntegrity` already existed (`SYSTEM`, `WORKSPACE_UNTRUSTED`,
  `EXTERNAL_UNTRUSTED`) before this work, but nothing combined multiple
  values — `tool_result_should_arm_gate` collapsed everything non-SYSTEM to
  the same boolean outcome.
- `docs/workstreams/` did not exist anywhere in the repo; this repo's
  existing spec-doc convention is `specs/*.md`.
- `OperationsNote` (`core/database.py:1841`, table `operations_notes`) has a
  centralized schema (one SQLAlchemy model file) but no centralized read
  function — `mcp_servers/ops_server.py`, `routes/operations/operations_routes.py`,
  and `src/projects_manager.py` each query it directly.
- Neither `operations_notes` nor `Note` currently has an `integrity` or
  `source_ref` column.
- Four pre-existing, unrelated test failures found during regression checks:
  `manage_projects` missing from `KNOWN_CAPABILITY_TOOLS`, a circular import
  in `src.tool_schemas`, a `cp1252` decode error, and (separately) an
  `ImportError` collecting `tests/test_ops_server_request_building.py` for a
  missing `_attention_params` in `mcp_servers/ops_server.py`. None reference
  `ResultIntegrity` or anything touched in this session; consistent with
  concurrent work on the project/ops-server code from another agent.
- Root `spec.md` (untracked, repo root) is an unrelated notes/lightbox spec,
  not a draft of this workstream.

## Branch merge (2026-09-01)

Merged `daily-driver`, `local-agent-1`, and `dev` into `local-agent-2` (all
local, clean fast-forward/auto-merge, zero conflicts — `tool_capabilities.py`
and `tool_execution.py` are untouched on every other branch; `local-agent-1`'s
`core/database.py` changes are in unrelated line ranges).

Relevant discoveries:
- `docs/workstreams/00-PROTOCOL.md` now exists (from `daily-driver`) — the
  tier-marker/evidence protocol the original stage instructions referenced.
  Non-negotiable stated there: "never operates on a live/production data
  store directly — copy first, work on the copy."
- Sibling workstream **ws-01 "Phone Database Recoverability & Liveness"**
  shipped a real, operational hourly backup pipeline (`phone/ws01_backup_db.sh`
  + `ws01_snapshot.py`: `VACUUM INTO` → verify → zstd → rclone to Drive).
  Confirmed live: `rclone listremotes` shows `gdrive:` configured.
- ws-01's research corrects a ws-02 assumption: the live DB does not hold
  Bil Weekend customer PII (that's Supabase, fetched live) — it holds
  `email_accounts`' real IMAP/SMTP passwords + OAuth tokens, plus
  `chat_messages`, `notes`, `documents`. Relevant to Q9's entry-point table.
- `local-agent-1` added phone-deploy tooling: `scripts/pull_and_restart_phone.py`
  (git-push based) and `scripts/sync_code_to_phone.py` (SFTP-based, no git
  involved) — used the latter's pattern for this session's phone deploy.

## Phone deploy (2026-09-01)

Deployed the Q1 storage-layer hook (combiner, `ACTIVE_RUN_SECURITY`, ORM
`load` hook) to the live phone instance. No DB migration needed — I1's
fail-closed rule means the code works correctly with zero schema changes
(every row without an `integrity` column reads back `EXTERNAL_UNTRUSTED`).

Steps taken, in order:
1. Triggered a fresh ws-01 backup (`app_db_20260901T115539Z.zst` uploaded to
   Drive) before touching anything, per 00-PROTOCOL.md's copy-first rule —
   belt-and-suspenders, since this deploy doesn't touch the DB at all.
2. SFTP-pushed `core/database.py`, `src/tool_capabilities.py`,
   `src/tool_execution.py` into the phone's proot Ubuntu checkout
   (`/root/odysseus`), byte-size-verified against the local files.
3. Import-checked the pushed files against the phone's actual venv before
   restarting — passed.
4. Restarted (`pkill -9 -f uvicorn` + the existing `Start_All.sh` shortcut).
5. Verified: `ps aux` shows the new process, the app's own log shows normal
   startup (embeddings, ChromaDB, MCP servers) and live 200 OK traffic
   resuming, and a direct `curl` from the phone to itself returned `302`
   (healthy). One transient `[Errno 98] address already in use` appeared
   from an earlier duplicate start attempt racing the kill; the process that
   actually bound the port came up clean and is the one currently serving.

## Not done / open

- Stage-1-style full archaeology (every table/collection, every read path,
  the end-to-end laundering trace, Q2–Q9) was not completed — this session's
  code work covered only Q1's boundary mechanism.
- No `integrity`/`source_ref` migration has been written or run anywhere.
- The ORM hook observes reads only inside `execute_tool_block`'s scope; a DB
  read elsewhere in `agent_loop.py` is not yet attributed to a run.
- Full-suite regression run completed: 5648 passed, 168 failed, 13 skipped,
  22 errors, in 21m17s. Grepped the failure/error list for `tool_capabilities`,
  `tool_execution`, `database.py`, `ACTIVE_RUN_SECURITY`, `ResultIntegrity`,
  and the new test file names — zero matches. None of the 190 failures/errors
  touch anything changed in this session; sampled failure names (searxng
  settings migration, shell_routes AppleSilicon/docker-socket tests,
  tool_path_confinement, code_nav_tools `FileNotFoundError`) point to
  pre-existing/environment causes, not this change.
- `docs/workstreams/ws-02/research.md`, `spec.v2.md`, and `deviations.md`
  from the original stage plan were never written — the #frame/#research/
  #design/#spec modes used in this session excluded file mutation, so those
  stages happened in conversation only, not on disk.
