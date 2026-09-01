# System Activity & Non-Chat Query Logging Subsystem Specification

Last updated: local-agent-1@12a1c08 | 2026-09-01

## Scope

- Backend Models: core/database.py (SystemQueryLog ORM model).
- Central Logger Engine: src/system_logger.py (log_system_query, get_system_logs, get_system_log_stats, prune_system_logs).
- REST Route Surfaces: routes/system/activity_log_routes.py (GET /api/system/activity-logs, GET /api/system/activity-logs/stats, DELETE /api/system/activity-logs/clear).
- Application Integration: app.py (setup_activity_log_routes).
- Frontend UI Hub: static/js/activityLog.js, static/index.html (#tool-activity-log-btn), static/app.js, static/js/modalManager.js.
- Telemetry Call Sites:
  - Projects: routes/projects/projects_routes.py (creation, updates, workspace AI summarization).
  - Tasks: src/task_scheduler.py (scheduled job run completions).
  - Email: src/builtin_actions.py (inbox auto-summaries and auto-draft reply passes).

---

## Architectural Principles & Invariants

1. **Non-Chat Isolation**:
   - Interactive user chat turns (POST /api/chat, /ws/chat) are recorded exclusively in session_messages and never written to system_query_logs.
   - system_query_logs is reserved strictly for background tasks, module automations, document queries, tool executions, and scheduled operations.

2. **Deduplication & 10-Minute Stacking**:
   - Automated background jobs (such as email pollers or task checks) that run frequently and produce unchanged outputs within a 10-minute window do not insert duplicate rows.
   - Matching recent queries increment repeat_count on the existing row, keeping the database compact and readable.

3. **Storage Retention Bounds**:
   - Hard cap: 10,000 maximum entries in system_query_logs.
   - Default TTL: 30 days.
   - Older or excess records are automatically pruned during database operations or via explicit DELETE /api/system/activity-logs/clear.

4. **Multi-User Ownership**:
   - Queries executed on behalf of a specific user store owner. Admin users and unauthenticated fallback requests store "default" / NULL with universal query visibility.

---

## Data Schema (system_query_logs)

| Field | Type | Description |
|---|---|---|
| id | String(64) | Unique query identifier (e.g. log_d207df361099) |
| timestamp | DateTime | UTC timestamp of event creation / update |
| module | String(64) | Originating module (projects, tasks, email, operations, etc.) |
| action | String(64) | Action name (summarize_project, task_run, summarize_emails, etc.) |
| target_id | String(128) | Optional target ID (project ID, task ID) |
| target_name | String(256) | Human-readable target name |
| query_type | String(32) | Invocation type (llm, system, tool, fallback) |
| model | String(128) | Model identifier used (gemma4:31b, phi4-mini, etc.) |
| endpoint_url | String(512) | Provider endpoint URL |
| prompt_preview | Text | Prompt or input payload snippet |
| result_preview | Text | Generated result or output snippet |
| status | String(32) | completed, running, error, fallback, halted |
| duration_ms | Integer | Execution duration in milliseconds |
| tokens_used | Integer | Approximate token count |
| error | Text | Error traceback or diagnostics |
| repeat_count | Integer | Repetition count within deduplication window |
| metadata_json | JSON | Extended key-value metadata |
| owner | String(128) | Username ownership |

---

## Frontend Architecture

1. **Launcher**:
   - Sidebar tool item #tool-activity-log-btn in static/index.html.
   - Visual running activity dot #activity-log-indicator indicates active in-flight queries.

2. **Modal Hub (#activity-log-modal)**:
   - Draggable header via makeWindowDraggable.
   - Real-time statistics banner (Total Queries, Running, Errors, Avg Latency).
   - Module filter chips with live counts.
   - Status selector dropdown and text search bar.
   - Expandable accordion rows with payload inspector, markdown preview, diagnostics, and raw metadata JSON.
   - Auto-polling at 3-second intervals while open, and 10-second background dot polling while minimized/closed.
