# Odysseus — Handoff

Written 2026-08-30 by a Claude Code session running on the laptop side ("Brains"), for whichever
coding agent picks up work on the phone side ("Body"). Self-contained — does not assume you have
access to the laptop's SYSTEM_RECORD.md.

## Guardrails (inherited — do not loosen)

- Writes stay inside this proot guest sandbox: local files, queue entries, on-device drafts.
  Nothing gets written to or sent via Google — reads against live Workspace/Sheets are fine,
  only writing is fenced.
- `ToolRunSecurityContext` (src/agent_loop.py) is not to be loosened to make a check pass. If a
  task requires loosening it, treat that task as blocked, not done.
- The phone is the host. Other machines (laptop, etc.) only drive it over SSH — don't invert that.
- Normal operating conditions are assumed (phone reachable, a GPU host up). A queue-only/no-op run
  is not a valid pass for anything described below as "working."

## Sync

This file lives at the repo root and is kept in sync via git: `origin` =
`https://github.com/RybzXx/odysseus.git`, branch `daily-driver`. Commit changes to it (and to code)
normally; `git pull` before editing so you're not working from a stale base.

## System, condensed

Odysseus is a self-hosted AI assistant (FastAPI/uvicorn) running in a proot-distro Ubuntu guest on
an Android phone (Samsung S24 Ultra) under Termux — no systemd, no Docker. Supervision is via
`~/.termux/boot/start_linux.sh` plus a `supervise_services.sh` watchdog. A laptop ("Brains", RTX
3070) provides model inference over Tailscale; the phone ("Body") is the always-on host. MagicDNS
doesn't resolve from Termux — everything uses literal tailnet IPs.

Five modularity seams were the throughline of the build: model endpoint, runtime host, transport,
lifecycle, and supervision. `ODYSSEUS_DATA_DIR` was relocated out of the app directory so the
container is disposable (this is the seam most re-verified below).

### Revision history (Rev A–M, from SYSTEM_RECORD.md)

- **A–D** — baseline: split-brain architecture, proot-distro guest, watchdog supervision,
  `ODYSSEUS_DATA_DIR` relocation.
- **E** — hybrid graphics/AI mode.
- **F** — empty model store fixed; Google Workspace integration added.
- **G** — email tool patches: `odysseus-list-pool` (routes/email_routes.py),
  `odysseus-keepalive-endpoints` (app.py), `odysseus-email-tool-dispatch` (src/tool_execution.py).
- **H** — empty/truncated LLM replies fixed: `odysseus-local-served-context` (src/model_context.py),
  `odysseus-nonstreaming-call-path` (src/llm_core.py), `odysseus-tool-fence-inline-json`
  (src/tool_parsing.py).
- **I** — cloud models, tables, keep-alive; markdown table patches:
  `odysseus-table-leading-newline`, `odysseus-table-inline-placeholder-guard`,
  `odysseus-table-escaped-pipe` (all static/js/markdown*).
- **J** — benchmark harness, N=5.
- **K** — AI mode widened.
- **L** — VRAM pooling correction: llama.cpp RPC pooling across two laptops on port 8080.
- **M** — pooled inference measured; found a defect where Ollama's blob storage path diverges
  from upstream's expected GGUF path.

All nine patches above are marker-delimited, idempotent source patchers with timestamped
`.bak-*` backups — see the patcher scripts (`odysseus_*.py`) alongside SYSTEM_RECORD.md on the
laptop if you need their exact diffs.

## Findings — behavioral re-verification (this session, 2026-08-30)

Read-only pass re-checking every claim SYSTEM_RECORD marks Verified, oracle = the record's own
claims, scope = phone + laptop + ops seam. Confidence labeled per item.

**Phone runtime — confirmed healthy.** uvicorn on :7000, chroma on :8100, 4 MCP servers up,
watchdog pid 20584 alive, 302 response in 20ms, 49 days uptime. The `ODYSSEUS_DATA_DIR` seam holds.

**Git state — confirmed.** Depth-1 shallow clone, `daily-driver` branch, HEAD `c82226d`
("feat(plan-mode): derive mutators from the capability table"). `origin` = `RybzXx/odysseus`
(fork, push+fetch), `upstream` = `odysseus-dev/odysseus`. `dev` remote-tracking branch sits at
`c9dd68d` — consistent with the "pinned to upstream c9dd68d8, ~8 commits on top" framing, now
corroborated (previously this claim wasn't independently verifiable). This was checked against
the **laptop's** clone; the phone clone's remote/branch state was not re-checked this session
(see Unknowns).

**Patch markers — 3 of 9 MISSING, confirmed (as of last live check, not re-verified today):**
`odysseus-list-pool`, `odysseus-email-tool-dispatch`, `odysseus-tool-fence-inline-json`. No
`.bak-*` files exist anywhere in the tree. Two of the three look absorbed upstream — the
`Unknown tool type` string is gone and `tool_parsing.py` has a newer parser — but
`odysseus-list-pool` has no replacement concurrency primitive in `routes/email_routes.py`; this
one looks lost, not absorbed (probable, not confirmed).

**Ambient scheduling — mixed.** The three enabled email tasks fire on time and do real work:
scanned 98 · urgent 2 · reply-soon 23 · trivial 73, 46 tags applied, 4 replies drafted
(draft-only, per `_email_auto_reply_draft_only` in `email_pollers.py`). But `Email Calendar
Events` and `Calendar Classify Events` are ACTIVE in the scheduler despite
`src/task_scheduler.py` defaulting all six email/calendar tasks to `ship_paused: True`, and both
have `run_count = 0, last_run = None` — someone or something flipped them on and they've never
actually fired (unknown who/why). Task runs report `status: success` even when an account errors
(observed: `[Book Bil Weekend] Error: The read operation timed out`, 14m56s duration). Saved
classification counts were observed to drift 98 → 1 → 0 across runs while still applying 46 tags
— idempotence or silent loss, not determined.

**Security boundary — confirmed, with a gap.** `ToolRunSecurityContext`
(`src/agent_loop.py:3462`) is the only construction site of the tool-gate; verified live that all
16 email tools flip `allow → BLOCK` after a `read_email` call in the manually-driven agent path.
But the ambient email lane (`builtin_actions.py:1025` → `email_pollers.py:_run_auto_summarize_once`)
never constructs a `ToolRunSecurityContext` at all — it bypasses the gate structurally. Its only
safety net is the separate `_email_auto_reply_draft_only` flag. This is a confirmed architectural
gap, not a bug in either mechanism individually.

**Laptop side — confirmed, matches record.** `OLLAMA_HOST=0.0.0.0:11434`, `KEEP_ALIVE=10m`,
`CONTEXT_LENGTH=8192` (matches phone-side 8192), `OLLAMA_MODELS=D:\ollama-models`. Ollama 0.33.0,
16 models, `/api/ps` empty at idle. Pooled llama.cpp on :8080 is up and reproduces the Rev M
blob-path defect live. `model_endpoints` table now has 3 enabled rows; Rev A's disabled-default
defect is gone. `supports_tools` is still NULL/0 on all endpoints, so fenced (not native)
tool-call parsing stays load-bearing.

**Ops seam (read side) — confirmed.** Pricing rulebook resolves under the agent's allowed roots
(`ODYSSEUS_DATA_DIR`, `/tmp`); 36 files, 0 drift as of last sync check.

**Untested asset — confirmed, unresolved.** The fork carries 808 files under `tests/` with
pytest 9.1.1 available in the guest's venv, including `tests/test_external_context_tool_gate.py`
— directly relevant to the security-boundary gap above. Not mentioned anywhere in SYSTEM_RECORD;
no evidence it has ever been run on-device.

**Timezone note.** Termux's own clock and the proot guest's clock were observed skewed by ~4
hours. Always read the clock from inside the guest when reasoning about scheduler timing —
reading Termux's clock alone produces false "the scheduler stopped firing" conclusions.

## Unknowns (open)

1. Does the shipped pytest suite pass in the guest? Never run, per above.
2. Was `odysseus-list-pool` deliberately dropped, or lost in a rebase?
3. Who activated `Email Calendar Events` / `Calendar Classify Events`, and why have they never run?
4. Is the 98→1→0 saved-classification drift idempotence or silent data loss?
5. How stale is the laptop's pricing JSON relative to the live Google Sheet?
6. Is the `Book Bil Weekend` IMAP timeout persistent or intermittent?
7. Is the shallow clone (depth 1) intentional, or should it be un-shallowed?
8. Does the phone-side clone's `origin`/branch match the laptop's (`RybzXx/odysseus`,
   `daily-driver`)? Not re-checked this session — SSH (port 8022) was refused (another instance
   was using it) and `adb`'s Termux `RUN_COMMAND` path is blocked by a `dangerous`-level Android
   permission (`com.termux.permission.RUN_COMMAND`) that the `adb shell`/`com.android.shell`
   identity can't hold, so `pm grant` no-ops. Confirm on next live access.

## Not yet done

SYSTEM_RECORD Rev N (fix-as-found, oracle = the record's own Verified claims) has not been
started — this file is a research handoff, not the fix pass itself.
