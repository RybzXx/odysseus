// static/js/operations.js
//
// Human-viewable panel over the Bil Weekend operations worklist — the same
// data mcp_servers/ops_server.py exposes to agents. Talks to
// routes/operations/operations_routes.py, which reuses that module's merge
// and staging logic, so there is exactly one worklist and exactly one
// write queue whether a change comes from an agent or from this panel.
//
// Rebuilt against Bil Weekend's actual admin source (OperationsWorklist.tsx,
// FollowUpBlock.tsx, operationsWorklist.ts, antiAbuse.ts — read directly
// during a research pass, not guessed): Table is the primary view, matching
// the real site's structure (a filtered table, not a board); Board is kept
// as a secondary, Odysseus-only view. Neither view writes Supabase directly
// — editing stages a local patch (see Push view), matching neither the real
// site's direct-write model nor this session's earlier paused-501 design,
// but reusing this session's own OperationsNote pattern (agent/human write
// locally, nothing touches Bil Weekend until a human acts on it).
//
// jKanban (Apache-2.0, vendored at /static/lib/jkanban.min.js, bundles
// Dragula for drag/drop) supplies the Board view's column/drag chrome.
// Loaded on first Board render, matching how markdown.js lazy-loads
// Mermaid/KaTeX.

import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';

const JKANBAN_JS = '/static/lib/jkanban.min.js';
const JKANBAN_CSS = '/static/lib/jkanban.min.css';

const STATUSES = ['New', 'In Progress', 'Replied', 'On Hold', 'Confirmed', 'Rejected'];
const OPEN_STATUSES = ['New', 'In Progress', 'Replied', 'On Hold'];
// jKanban board ids can't safely carry spaces; slug for the DOM, map back for the API.
const STATUS_SLUG = Object.fromEntries(STATUSES.map((s) => [s, s.toLowerCase().replace(/\s+/g, '-')]));
const SLUG_STATUS = Object.fromEntries(STATUSES.map((s) => [s.toLowerCase().replace(/\s+/g, '-'), s]));

// Matches ops_server.py's _JSONB_SOURCES keys plus "queue".
const SOURCES = ['booking', 'contact', 'curated', 'queue'];
const SOURCE_LABELS = { booking: 'Registration', contact: 'Contact', curated: 'Curated', queue: 'Queue' };

const FLAGS = ['overdue', 'untouched', 'suspected'];
const FLAG_LABELS = { overdue: 'Overdue', untouched: 'Untouched', suspected: 'Suspected' };

const MODERATIONS = ['flagged', 'spam'];

// One patch field -> its human label, for the Push view's "what changed" line.
const PATCH_FIELD_LABELS = { status: 'Status', operator: 'Operator', next_action_date: 'Next action', moderation: 'Moderation' };

let _open = false;
let _modal = null;
let _rowsByKey = new Map();       // worklist key -> row, for expected_updated_at when staging
let _lastRows = null;             // last successful fetch — reused across view switches, no refetch
let _notesByKey = new Map();      // worklist key -> note[]
let _stagedByKey = new Map();     // worklist key -> staged-change[], not yet pushed
let _viewMode = 'table';          // 'board' | 'table' | 'push' — Table is the site-matching default
let _statusFilter = new Set();    // empty = no constraint, like the real site's axes
let _flagFilter = new Set();
let _sourceFilter = new Set();
let _operatorFilter = new Set();
let _spamOnly = false;
let _search = '';                 // not persisted across close — matches the real site keeping search local
let _selectedKeys = new Set();    // Table row selection for bulk moderation — not persisted
let _openFilterDim = null;        // which filter dropdown ('status'|'flags'|'source'|'operator') is open, or null
let _filterCloseHandler = null;   // the single outside-click listener that closes an open filter dropdown
let _jkanbanPromise = null;
let _stylesInjected = false;

function _esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function _loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.addEventListener('load', () => resolve(), { once: true });
    script.addEventListener('error', () => reject(new Error('Failed to load ' + src)), { once: true });
    document.head.appendChild(script);
  });
}

function _loadStylesheet(href) {
  return new Promise((resolve) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    link.addEventListener('load', () => resolve(), { once: true });
    link.addEventListener('error', () => resolve(), { once: true });
    document.head.appendChild(link);
  });
}

function _ensureJKanban() {
  return (_jkanbanPromise ??= Promise.all([_loadScript(JKANBAN_JS), _loadStylesheet(JKANBAN_CSS)])
    .then(() => {
      if (!window.jKanban) throw new Error('jKanban global missing after load');
      return window.jKanban;
    })
    .catch((err) => {
      _jkanbanPromise = null;
      throw err;
    }));
}

function _injectStyles() {
  if (_stylesInjected) return;
  _stylesInjected = true;
  const style = document.createElement('style');
  style.id = 'ops-styles';
  style.textContent = `
    #operations-modal .ops-modal-content { width: min(1200px, 94vw); height: min(720px, 88vh); display: flex; flex-direction: column; overflow: hidden; }
    #operations-modal .modal-body { flex: 1; overflow: hidden; padding: 0; }
    #operations-modal #ops-body { height: 100%; display: flex; flex-direction: column; overflow: hidden; }
    #operations-modal .ops-loading, #operations-modal .ops-error { padding: 24px; color: var(--fg-muted, #888); }
    #operations-modal .ops-error { color: var(--color-danger, var(--accent-error, #d33)); }
    #operations-modal .ops-view-toggle { display: flex; gap: 4px; margin-left: auto; margin-right: 12px; }
    #operations-modal .ops-view-btn { background: var(--bg-elev, #242424); border: 1px solid var(--border, #333); color: var(--fg-muted, #888); border-radius: 6px; font-size: 11px; padding: 4px 10px; cursor: pointer; position: relative; }
    #operations-modal .ops-view-btn.active { color: var(--fg, #eee); border-color: var(--accent, #e8a33d); }
    #operations-modal .ops-view-btn .ops-badge { background: var(--accent, #e8a33d); color: #111; border-radius: 8px; font-size: 9px; font-weight: 700; padding: 0 4px; margin-left: 4px; }

    /* ---- Board (secondary view) ---- */
    #operations-modal #ops-kanban { flex: 1; min-height: 0; }
    #operations-modal #ops-kanban .kanban-container { height: 100%; overflow-x: auto; overflow-y: hidden; white-space: nowrap; padding: 12px; background: var(--bg, #1a1a1a); }
    #operations-modal .kanban-board { display: inline-flex; flex-direction: column; float: none; width: 260px; height: 100%; margin-right: 12px; border-radius: 8px; background: var(--bg-elev, #242424); border: 1px solid var(--border, #333); vertical-align: top; white-space: normal; }
    #operations-modal .kanban-board header { border-bottom: 1px solid var(--border, #333); flex-shrink: 0; }
    #operations-modal .kanban-title-board { color: var(--fg, #eee); font-size: 13px; }
    #operations-modal .ops-col-count { color: var(--fg-muted, #888); font-weight: 400; margin-left: 4px; }
    #operations-modal .kanban-drag { flex: 1; min-height: 0; overflow-y: auto; }
    #operations-modal .kanban-item { background: var(--bg, #1a1a1a); border: 1px solid var(--border, #333); border-radius: 6px; color: var(--fg, #eee); font-size: 12px; white-space: normal; }
    #operations-modal .kanban-item.ops-card-staged { opacity: 0.7; border-style: dashed; }
    #operations-modal .kanban-item.ops-card-staged::after { content: 'staged — not pushed'; display: block; margin-top: 6px; font-size: 10px; color: var(--accent, #e8a33d); }

    /* ---- Shared card/row bits (Board cards, Table cells, notes, editor) ---- */
    #operations-modal .ops-card-title { font-weight: 600; margin-bottom: 4px; }
    #operations-modal .ops-card-contact { color: var(--fg-dim, #aaa); font-size: 11px; margin-bottom: 4px; }
    #operations-modal .ops-card-meta { color: var(--fg-muted, #888); font-size: 11px; }
    #operations-modal .ops-risk { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }
    #operations-modal .ops-risk-confirmed-spam { background: var(--color-danger, #d33); }
    #operations-modal .ops-risk-suspected { background: var(--accent, #e8a33d); }
    #operations-modal .ops-risk-clean, #operations-modal .ops-risk-not-scored { background: transparent; }
    #operations-modal .ops-card-notes { margin-top: 6px; border-top: 1px dashed var(--border, #333); padding-top: 6px; }
    #operations-modal .ops-card-note { font-size: 11px; color: var(--fg-dim, #aaa); margin-bottom: 3px; }
    #operations-modal .ops-card-note b { color: var(--fg, #eee); }
    #operations-modal .ops-note-editor { margin-top: 6px; }
    #operations-modal .ops-note-editor textarea, #operations-modal .ops-editor textarea { width: 100%; box-sizing: border-box; background: var(--bg, #1a1a1a); color: var(--fg, #eee); border: 1px solid var(--border, #333); border-radius: 4px; font: inherit; font-size: 11px; padding: 4px; resize: vertical; }
    #operations-modal .ops-note-editor-actions { display: flex; gap: 6px; margin-top: 4px; }
    #operations-modal button.ops-chip, #operations-modal .ops-note-editor-actions button, #operations-modal .ops-editor-actions button, #operations-modal .ops-status-pill, #operations-modal .ops-mod-pill { font-size: 11px; padding: 3px 10px; border-radius: 12px; border: 1px solid var(--border, #333); background: var(--bg-elev, #242424); color: var(--fg-muted, #888); cursor: pointer; }
    #operations-modal .ops-note-save, #operations-modal .ops-editor-save { border-color: var(--accent, #e8a33d); color: var(--fg, #eee); }
    #operations-modal .ops-status-pill.active { background: var(--accent, #e8a33d); color: #111; border-color: var(--accent, #e8a33d); }
    #operations-modal .ops-mod-pill.active { background: var(--color-danger, #d33); color: #fff; border-color: var(--color-danger, #d33); }

    /* ---- Table (primary view) ---- */
    #operations-modal .ops-table-view { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
    #operations-modal .ops-filters { flex-shrink: 0; padding: 10px 14px; border-bottom: 1px solid var(--border, #333); display: flex; flex-direction: column; gap: 6px; }
    #operations-modal .ops-filters-row1 { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 6px; }
    #operations-modal .ops-filter-dropdown { position: relative; }
    #operations-modal .ops-filter-toggle { font-size: 11px; padding: 3px 10px; border-radius: 12px; border: 1px solid var(--border, #333); background: var(--bg-elev, #242424); color: var(--fg-muted, #888); cursor: pointer; }
    #operations-modal .ops-filter-toggle.active { background: var(--accent, #e8a33d); color: #111; border-color: var(--accent, #e8a33d); }
    #operations-modal .ops-filter-caret { font-size: 9px; opacity: 0.8; }
    #operations-modal .ops-filter-panel { position: absolute; top: calc(100% + 4px); left: 0; z-index: 5; min-width: 190px; max-height: 260px; overflow-y: auto; background: var(--bg-elev, #242424); border: 1px solid var(--border, #333); border-radius: 8px; padding: 6px; box-shadow: 0 6px 18px rgba(0,0,0,0.35); }
    #operations-modal .ops-filter-option { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--fg, #eee); padding: 4px 6px; border-radius: 4px; cursor: pointer; white-space: nowrap; }
    #operations-modal .ops-filter-option:hover { background: var(--bg, #1a1a1a); }
    #operations-modal .ops-filter-option .ops-chip-count { margin-left: auto; opacity: 0.6; }
    #operations-modal .ops-chip.active { background: var(--accent, #e8a33d); color: #111; border-color: var(--accent, #e8a33d); }
    #operations-modal .ops-chip .ops-chip-count { opacity: 0.7; margin-left: 2px; }
    #operations-modal .ops-filters-row2 { display: flex; align-items: center; gap: 10px; }
    #operations-modal .ops-search-input { flex: 1; max-width: 280px; background: var(--bg, #1a1a1a); border: 1px solid var(--border, #333); color: var(--fg, #eee); border-radius: 6px; padding: 5px 10px; font-size: 12px; }
    #operations-modal .ops-clear-filters { font-size: 11px; color: var(--fg-muted, #888); background: none; border: none; cursor: pointer; text-decoration: underline; }
    #operations-modal .ops-bulk-bar { flex-shrink: 0; padding: 8px 14px; background: var(--bg-elev, #242424); border-bottom: 1px solid var(--border, #333); display: flex; align-items: center; gap: 10px; font-size: 12px; }
    #operations-modal .ops-table-scroll { flex: 1; min-height: 0; overflow: auto; }
    #operations-modal table.ops-table { width: 100%; border-collapse: collapse; font-size: 12px; color: var(--fg, #eee); min-width: 820px; }
    #operations-modal table.ops-table th { text-align: left; color: var(--fg-muted, #888); font-weight: 600; font-size: 10px; text-transform: uppercase; padding: 6px 10px; border-bottom: 1px solid var(--border, #333); position: sticky; top: 0; background: var(--bg, #1a1a1a); }
    #operations-modal table.ops-table td { padding: 8px 10px; border-bottom: 1px solid var(--border, #333); vertical-align: top; }
    #operations-modal table.ops-table tr.ops-row:hover { background: var(--bg-elev, #242424); cursor: pointer; }
    #operations-modal .ops-status-badge { padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 700; text-transform: uppercase; background: var(--bg-elev, #242424); border: 1px solid var(--border, #333); }
    #operations-modal .ops-editor-cell { background: var(--bg-elev, #1e1e1e); }
    #operations-modal .ops-editor { padding: 10px 4px; }
    #operations-modal .ops-editor-statuses { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 10px; }
    #operations-modal .ops-editor-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
    #operations-modal .ops-editor-row label, #operations-modal .ops-field-label { display: block; font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--fg-muted, #888); margin-bottom: 3px; }
    #operations-modal .ops-editor-row select, #operations-modal .ops-editor-row input { width: 100%; box-sizing: border-box; background: var(--bg, #1a1a1a); color: var(--fg, #eee); border: 1px solid var(--border, #333); border-radius: 4px; padding: 5px 8px; font-size: 12px; }
    #operations-modal .ops-editor-moderation { display: flex; gap: 6px; align-items: center; margin-bottom: 10px; }
    #operations-modal .ops-editor-actions { display: flex; gap: 8px; align-items: center; }
    #operations-modal .ops-editor-hint { font-size: 11px; color: var(--fg-muted, #888); }
    #operations-modal .ops-summary-chip { color: var(--fg-muted, #888); font-size: 11px; }
    #operations-modal .ops-full-detail { margin: 4px 0 10px; border-top: 1px dashed var(--border, #333); padding-top: 8px; }
    #operations-modal .ops-detail-table { width: 100%; border-collapse: collapse; font-size: 11px; }
    #operations-modal .ops-detail-table td { padding: 3px 6px; border-bottom: 1px solid var(--border, #2a2a2a); vertical-align: top; }
    #operations-modal .ops-detail-key { color: var(--fg-muted, #888); font-weight: 600; white-space: nowrap; width: 40%; }
    #operations-modal .ops-detail-val { color: var(--fg, #eee); word-break: break-word; }
    #operations-modal .ops-detail-json { white-space: pre-wrap; word-break: break-word; font-size: 10px; margin: 0; }
    #operations-modal .ops-detail-toggle-empty { display: inline-block; margin: 6px 0; }
    #operations-modal .ops-detail-table-empty { margin-top: 6px; }

    /* Mobile: below 640px, swap the table for a card list — two DOM trees,
       not one reflowed table, matching BookingsManager.tsx's own hidden
       md:block / md:hidden split. */
    #operations-modal .ops-table-desktop { display: block; }
    #operations-modal .ops-table-mobile { display: none; }
    @media (max-width: 640px) {
      #operations-modal .ops-table-desktop { display: none; }
      #operations-modal .ops-table-mobile { display: block; }
    }
    #operations-modal .ops-mobile-card { border-bottom: 1px solid var(--border, #333); padding: 10px 14px; }
    #operations-modal .ops-mobile-card-head { display: flex; justify-content: space-between; align-items: center; cursor: pointer; }

    /* ---- Push view ---- */
    #operations-modal .ops-push-view { flex: 1; min-height: 0; overflow: auto; padding: 14px; }
    #operations-modal .ops-push-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
    #operations-modal .ops-push-item { border: 1px solid var(--border, #333); border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; font-size: 12px; }
    #operations-modal .ops-push-item.ops-conflict { border-color: var(--color-danger, #d33); }
    #operations-modal .ops-push-item-head { display: flex; justify-content: space-between; align-items: center; }
    #operations-modal .ops-push-empty { padding: 40px; text-align: center; color: var(--fg-muted, #888); }
  `;
  document.head.appendChild(style);
}

// FastAPI's HTTPException bodies are {"detail": "..."} — surface that text
// instead of a bare status code, so "not configured" reads as "not
// configured" rather than "503".
async function _errorFromResponse(res, fallback) {
  let detail = null;
  try {
    const body = await res.json();
    detail = body && (body.detail || body.message);
  } catch (_) { /* body wasn't JSON — fall back below */ }
  return new Error(detail || (fallback + ' (' + res.status + ')'));
}

async function _fetchWorklist() {
  const res = await fetch('/api/operations', { credentials: 'same-origin' });
  if (!res.ok) throw await _errorFromResponse(res, 'Failed to load operations worklist');
  const data = await res.json();
  return data.items || data.rows || data.worklist || (Array.isArray(data) ? data : []);
}

async function _fetchFullRecord(key) {
  const res = await fetch('/api/operations/detail?key=' + encodeURIComponent(key), { credentials: 'same-origin' });
  if (!res.ok) throw await _errorFromResponse(res, 'Failed to load full record');
  const data = await res.json();
  return data.record;
}

async function _fetchAllNotes() {
  const res = await fetch('/api/operations/notes', { credentials: 'same-origin' });
  if (!res.ok) return new Map();
  const data = await res.json();
  const map = new Map();
  for (const n of (data.notes || [])) {
    if (!map.has(n.key)) map.set(n.key, []);
    map.get(n.key).push(n);
  }
  return map;
}

async function _postNote(key, text) {
  const res = await fetch('/api/operations/notes', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, text }),
  });
  if (!res.ok) throw await _errorFromResponse(res, 'Failed to save note');
  return res.json();
}

async function _fetchStaged() {
  const res = await fetch('/api/operations/staged', { credentials: 'same-origin' });
  if (!res.ok) return new Map();
  const data = await res.json();
  const map = new Map();
  for (const s of (data.staged || [])) {
    if (!map.has(s.key)) map.set(s.key, []);
    map.get(s.key).push(s);
  }
  return map;
}

async function _postStage(key, patch, expectedUpdatedAt) {
  const res = await fetch('/api/operations/stage', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, expected_updated_at: expectedUpdatedAt, ...patch }),
  });
  if (!res.ok) throw await _errorFromResponse(res, 'Failed to stage change');
  return res.json();
}

async function _deleteStaged(id) {
  const res = await fetch('/api/operations/staged/' + encodeURIComponent(id), {
    method: 'DELETE',
    credentials: 'same-origin',
  });
  if (!res.ok) throw await _errorFromResponse(res, 'Failed to discard staged change');
  return res.json();
}

async function _postPush() {
  const res = await fetch('/api/operations/push', { method: 'POST', credentials: 'same-origin' });
  if (!res.ok) throw await _errorFromResponse(res, 'Push failed');
  return res.json();
}

// ---------------------------------------------------------------------------
// Domain helpers — ported from Bil Weekend's own admin source this session,
// not invented. See ops_server.py's mirrors of the same logic server-side.
// ---------------------------------------------------------------------------

function _ageInDays(dateStr) {
  if (!dateStr) return null;
  const then = new Date(dateStr).getTime();
  if (Number.isNaN(then)) return null;
  return Math.max(0, Math.floor((Date.now() - then) / 86400000));
}

function _isOverdue(row) {
  if (!row.next_action_date) return false;
  if (!OPEN_STATUSES.includes(row.status)) return false;
  return row.next_action_date < new Date().toISOString().slice(0, 10);
}

function _isUntouched(row) {
  if (row.source === 'queue') return false;
  return row.status === 'New' && !row.operator && !row.next_action_date;
}

function _hasFlag(row, flag) {
  if (flag === 'overdue') return _isOverdue(row);
  if (flag === 'untouched') return _isUntouched(row);
  return row.risk === 'suspected';
}

// Any staged (not-yet-pushed) patch fields for a key, merged in staged order.
function _stagedPatchFor(key) {
  const items = (_stagedByKey.get(key) || []).filter((s) => !s.conflict);
  return items.reduce((acc, s) => ({ ...acc, ...s.patch }), {});
}

// Row + whatever's staged on top of it — what the editor should show, and
// what a card/row should render, so a pending local edit is visible before
// it's pushed.
function _effectiveRow(row) {
  return { ...row, ...(_stagedPatchFor(row.key)) };
}

function _matchesSearch(row, q) {
  if (!q) return true;
  const needle = q.toLowerCase();
  return [row.name, row.email, row.phone, row.operator, row.key, ...(row.summary || [])]
    .filter(Boolean)
    .some((v) => String(v).toLowerCase().includes(needle));
}

// OR within an axis, AND across axes — matches OperationsWorklist.tsx's
// matchesDimension. `except` lets a chip's own count exclude its own axis,
// so selecting a status doesn't drive every sibling status to zero.
function _matchesDimension(row, dimension, except) {
  if (dimension === except) return true;
  if (dimension === 'status') return _statusFilter.size === 0 || _statusFilter.has(row.status);
  if (dimension === 'flags') return _flagFilter.size === 0 || [...FLAGS].some((f) => _flagFilter.has(f) && _hasFlag(row, f));
  if (dimension === 'source') return _sourceFilter.size === 0 || _sourceFilter.has(row.source);
  if (dimension === 'operator') return _operatorFilter.size === 0 || (row.operator && _operatorFilter.has(row.operator));
  return true;
}

function _matchingExcept(pool, except) {
  return pool.filter((row) =>
    ['status', 'flags', 'source', 'operator'].every((d) => _matchesDimension(row, d, except))
    && _matchesSearch(row, _search));
}

// ---------------------------------------------------------------------------
// Notes (shared by Board cards and Table rows)
// ---------------------------------------------------------------------------

function _notesHtml(key) {
  return `<div class="ops-card-notes" data-notes-for="${_esc(key)}"></div>` +
    `<button type="button" class="ops-card-add-note" data-note-key="${_esc(key)}" style="margin-top:4px;">+ agent note</button>`;
}

function _wireNoteButtons(container) {
  container.querySelectorAll('.ops-card-add-note').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      _openNoteEditor(btn, container);
    });
  });
}

function _openNoteEditor(btn, container) {
  if (btn.nextElementSibling && btn.nextElementSibling.classList.contains('ops-note-editor')) return;
  const key = btn.dataset.noteKey;
  const editor = document.createElement('div');
  editor.className = 'ops-note-editor';
  editor.innerHTML = `
    <textarea rows="2" placeholder="Note…"></textarea>
    <div class="ops-note-editor-actions">
      <button type="button" class="ops-note-save">Save</button>
      <button type="button" class="ops-chip">Cancel</button>
    </div>`;
  editor.addEventListener('click', (e) => e.stopPropagation());
  btn.insertAdjacentElement('afterend', editor);
  btn.style.display = 'none';
  const textarea = editor.querySelector('textarea');
  textarea.focus();

  const close = () => { editor.remove(); btn.style.display = ''; };
  editor.querySelector('.ops-chip').addEventListener('click', close);
  editor.querySelector('.ops-note-save').addEventListener('click', async () => {
    const text = textarea.value.trim();
    if (!text) { close(); return; }
    try {
      const saved = await _postNote(key, text);
      if (!_notesByKey.has(key)) _notesByKey.set(key, []);
      _notesByKey.get(key).unshift(saved);
      _renderNotesFor(key, container);
      close();
    } catch (err) {
      console.warn('Operations: note save failed', err);
    }
  });
}

function _renderNotesFor(key, container) {
  const slot = container.querySelector(`.ops-card-notes[data-notes-for="${CSS.escape(key)}"]`);
  if (!slot) return;
  const notes = _notesByKey.get(key) || [];
  slot.innerHTML = notes.slice(0, 5)
    .map((n) => `<div class="ops-card-note"><b>${_esc(n.author)}:</b> ${_esc(n.text)}</div>`)
    .join('');
}

// ---------------------------------------------------------------------------
// Shared expand-in-place editor — status/operator/date/moderation, staged
// on Save. One component, used from both the Table and (implicitly, via
// drag) the Board.
// ---------------------------------------------------------------------------

function _operatorOptions() {
  const set = new Set();
  (_lastRows || []).forEach((r) => { if (r.operator) set.add(r.operator); });
  return [...set].sort();
}

// Full raw record (fetched fresh from Supabase, not the worklist's composed
// summary) for queue and curated requests — the two sources whose real
// detail (queue's flat columns; curated's full questionnaire) isn't
// otherwise on the worklist row at all.
// null/undefined/'' and empty arrays/objects carry no information — Supabase
// returns every column whether the submitter filled it in or not, and most
// requests leave most of the optional questionnaire fields untouched.
function _isEmptyDetailValue(v) {
  if (v === null || v === undefined || v === '') return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === 'object') return Object.keys(v).length === 0;
  return false;
}

function _detailRowHtml([k, v]) {
  const display = typeof v === 'object' && v !== null
    ? `<pre class="ops-detail-json">${_esc(JSON.stringify(v, null, 2))}</pre>`
    : _esc(String(v));
  return `<tr><td class="ops-detail-key">${_esc(k)}</td><td class="ops-detail-val">${display}</td></tr>`;
}

function _detailRowsHtml(record) {
  const entries = record && typeof record === 'object' ? Object.entries(record) : [];
  if (!entries.length) return '<div class="ops-card-meta">Empty record.</div>';

  const populated = entries.filter(([, v]) => !_isEmptyDetailValue(v));
  const empty = entries.filter(([, v]) => _isEmptyDetailValue(v));

  const populatedHtml = populated.length
    ? '<table class="ops-detail-table">' + populated.map(_detailRowHtml).join('') + '</table>'
    : '<div class="ops-card-meta">No populated fields.</div>';
  const emptyHtml = empty.length
    ? `<button type="button" class="ops-chip ops-detail-toggle-empty">Show ${empty.length} empty field${empty.length === 1 ? '' : 's'}</button>` +
      `<table class="ops-detail-table ops-detail-table-empty" hidden>${empty.map(_detailRowHtml).join('')}</table>`
    : '';
  return populatedHtml + emptyHtml;
}

// The toggle button and the empty-fields table it reveals are rebuilt fresh
// each time _detailRowsHtml runs, so this just wires the one button in the
// freshly-inserted markup — no state to preserve across re-renders.
function _wireDetailToggle(slot) {
  const btn = slot.querySelector('.ops-detail-toggle-empty');
  const table = slot.querySelector('.ops-detail-table-empty');
  if (!btn || !table) return;
  btn.addEventListener('click', () => {
    table.hidden = !table.hidden;
    const count = table.querySelectorAll('tr').length;
    btn.textContent = `${table.hidden ? 'Show' : 'Hide'} ${count} empty field${count === 1 ? '' : 's'}`;
  });
}

function _renderFullDetail(row, wrap) {
  if (row.source !== 'queue' && row.source !== 'curated') return;
  const slot = wrap.querySelector('.ops-full-detail');
  _fetchFullRecord(row.key)
    .then((record) => {
      if (!slot.isConnected) return; // editor was closed/replaced before the fetch resolved
      slot.innerHTML = '<div class="ops-field-label">Full record (live from Supabase)</div>' + _detailRowsHtml(record);
      _wireDetailToggle(slot);
    })
    .catch((err) => {
      if (!slot.isConnected) return;
      slot.innerHTML = `<div class="ops-field-label">Full record (live from Supabase)</div><div class="ops-error" style="padding:4px 0;">${_esc(err.message)}</div>`;
    });
}

function _renderEditor(row, container) {
  const eff = _effectiveRow(row);
  const draft = {
    status: eff.status, operator: eff.operator || '', next_action_date: eff.next_action_date || '',
    moderation: eff.moderation || null,
  };
  const wrap = document.createElement('div');
  wrap.className = 'ops-editor';
  wrap.innerHTML = `
    <div class="ops-editor-statuses">
      ${STATUSES.map((s) => `<button type="button" class="ops-status-pill${draft.status === s ? ' active' : ''}" data-status="${s}">${_esc(s)}</button>`).join('')}
    </div>
    <div class="ops-editor-row">
      <div>
        <span class="ops-field-label">Operator</span>
        <select class="ops-operator-select">
          <option value="">Unassigned</option>
          ${_operatorOptions().map((o) => `<option value="${_esc(o)}" ${o === draft.operator ? 'selected' : ''}>${_esc(o)}</option>`).join('')}
        </select>
      </div>
      <div>
        <span class="ops-field-label">Next action date</span>
        <input type="date" class="ops-date-input" value="${_esc(draft.next_action_date)}" />
      </div>
    </div>
    <div class="ops-editor-moderation">
      <span class="ops-field-label" style="margin:0;">Moderation</span>
      ${MODERATIONS.map((m) => `<button type="button" class="ops-mod-pill${draft.moderation === m ? ' active' : ''}" data-mod="${m}">${_esc(m)}</button>`).join('')}
    </div>
    <div class="ops-editor-actions">
      <button type="button" class="ops-editor-save ops-chip">Stage change</button>
      <button type="button" class="ops-chip ops-editor-cancel">Cancel</button>
      <span class="ops-editor-hint"></span>
    </div>
    ${(row.source === 'queue' || row.source === 'curated') ? `<div class="ops-full-detail"><div class="ops-field-label">Full record (live from Supabase)</div><div class="ops-loading" style="padding:6px 0;">Loading…</div></div>` : ''}
    <div class="ops-card-notes" data-notes-for="${_esc(row.key)}"></div>
    <button type="button" class="ops-card-add-note" data-note-key="${_esc(row.key)}">+ agent note</button>
  `;
  wrap.addEventListener('click', (e) => e.stopPropagation());

  wrap.querySelectorAll('.ops-status-pill').forEach((btn) => {
    btn.addEventListener('click', () => {
      draft.status = btn.dataset.status;
      wrap.querySelectorAll('.ops-status-pill').forEach((b) => b.classList.toggle('active', b === btn));
    });
  });
  wrap.querySelectorAll('.ops-mod-pill').forEach((btn) => {
    btn.addEventListener('click', () => {
      draft.moderation = draft.moderation === btn.dataset.mod ? null : btn.dataset.mod;
      wrap.querySelectorAll('.ops-mod-pill').forEach((b) => b.classList.toggle('active', draft.moderation === b.dataset.mod));
    });
  });
  wrap.querySelector('.ops-operator-select').addEventListener('change', (e) => { draft.operator = e.target.value; });
  wrap.querySelector('.ops-date-input').addEventListener('change', (e) => { draft.next_action_date = e.target.value; });

  const hint = wrap.querySelector('.ops-editor-hint');
  wrap.querySelector('.ops-editor-save').addEventListener('click', async () => {
    const patch = {};
    if (draft.status !== eff.status) patch.status = draft.status;
    if ((draft.operator || null) !== (eff.operator || null)) patch.operator = draft.operator || null;
    if ((draft.next_action_date || null) !== (eff.next_action_date || null)) patch.next_action_date = draft.next_action_date || null;
    if (draft.moderation !== (eff.moderation || null)) patch.moderation = draft.moderation;
    if (Object.keys(patch).length === 0) { hint.textContent = 'Nothing changed.'; return; }
    try {
      const saved = await _postStage(row.key, patch, row.updated_at || null);
      if (!_stagedByKey.has(row.key)) _stagedByKey.set(row.key, []);
      _stagedByKey.get(row.key).push(saved);
      hint.textContent = 'Staged — see Push to send it live.';
      _syncViewBadge();
    } catch (err) {
      hint.textContent = err.message;
    }
  });
  wrap.querySelector('.ops-editor-cancel').addEventListener('click', () => _renderCurrentView());

  _wireNoteButtons(wrap);
  container.appendChild(wrap);
  _renderNotesFor(row.key, wrap);
  _renderFullDetail(row, wrap);
}

function _syncViewBadge() {
  if (!_modal) return;
  const btn = _modal.querySelector('.ops-view-btn[data-view="push"]');
  if (!btn) return;
  const count = [..._stagedByKey.values()].reduce((n, arr) => n + arr.filter((s) => !s.conflict).length, 0);
  btn.querySelectorAll('.ops-badge').forEach((b) => b.remove());
  if (count > 0) btn.insertAdjacentHTML('beforeend', `<span class="ops-badge">${count}</span>`);
}

// ---------------------------------------------------------------------------
// Data load / view dispatch
// ---------------------------------------------------------------------------

async function _render() {
  const body = _modal.querySelector('#ops-body');
  body.innerHTML = '<div class="ops-loading">Loading worklist…</div>';

  let rows, notesByKey, stagedByKey;
  try {
    [rows, notesByKey, stagedByKey] = await Promise.all([_fetchWorklist(), _fetchAllNotes(), _fetchStaged()]);
  } catch (err) {
    body.innerHTML = `<div class="ops-error">${_esc(err.message)}</div>`;
    return;
  }

  _lastRows = rows;
  _notesByKey = notesByKey;
  _stagedByKey = stagedByKey;
  _rowsByKey = new Map(rows.map((r) => [r.key, r]));
  _selectedKeys = new Set();
  _renderCurrentView();
  _syncViewBadge();
}

function _visiblePool() {
  // Confirmed-spam excluded by default, everywhere — matches the real
  // site's own split. spamOnly flips which pool is being looked at.
  const live = (_lastRows || []).filter((r) => r.risk !== 'confirmed-spam');
  const spam = (_lastRows || []).filter((r) => r.risk === 'confirmed-spam');
  return _spamOnly ? spam : live;
}

function _renderCurrentView() {
  if (!_modal || !_lastRows) return;
  const body = _modal.querySelector('#ops-body');
  if (_viewMode === 'push') _renderPush(body);
  else if (_viewMode === 'board') _renderBoard(_matchingExcept(_visiblePool(), null), body);
  else _renderTable(body);
}

// ---------------------------------------------------------------------------
// Board (secondary view) — unfiltered by the Table's axes except spam.
// ---------------------------------------------------------------------------

function _cardHtml(row) {
  const eff = _effectiveRow(row);
  const title = (row.summary || []).join(' · ') || row.name || row.email || row.key;
  const contact = [row.name, row.email, row.phone].filter(Boolean).join(' · ');
  const meta = [eff.operator, _isOverdue(row) ? 'OVERDUE' : null].filter(Boolean).join(' · ');
  const risk = row.risk === 'suspected'
    ? '<span class="ops-risk ops-risk-suspected" title="Suspected spam"></span>' : '';
  return (
    `<div class="ops-card-title">${risk}${_esc(title)}</div>` +
    (contact ? `<div class="ops-card-contact">${_esc(contact)}</div>` : '') +
    (meta ? `<div class="ops-card-meta">${_esc(meta)}</div>` : '') +
    _notesHtml(row.key)
  );
}

function _syncColumnCounts(kanbanEl) {
  kanbanEl.querySelectorAll('.kanban-board').forEach((board) => {
    const countEl = board.querySelector('.ops-col-count');
    const drag = board.querySelector('.kanban-drag');
    if (countEl && drag) countEl.textContent = drag.querySelectorAll('.kanban-item').length;
  });
}

async function _renderBoard(rows, body) {
  body.innerHTML = '<div class="ops-loading">Loading board…</div>';
  try {
    await _ensureJKanban();
  } catch (err) {
    body.innerHTML = `<div class="ops-error">${_esc(err.message)}</div>`;
    return;
  }
  if (_viewMode !== 'board') return; // view changed while jKanban was loading

  body.innerHTML = '<div id="ops-kanban"></div>';
  const kanbanEl = body.querySelector('#ops-kanban');

  const boards = STATUSES.map((status) => {
    const inStatus = rows.filter((r) => _effectiveRow(r).status === status);
    return {
      id: STATUS_SLUG[status],
      title: `${_esc(status)} <span class="ops-col-count">${inStatus.length}</span>`,
      item: inStatus.map((r) => ({ id: r.key, title: _cardHtml(r) })),
    };
  });

  new window.jKanban({
    element: '#ops-kanban',
    boards,
    dropEl: async (el, target) => {
      const key = el.dataset.eid;
      const newStatus = SLUG_STATUS[target.parentNode?.dataset.id];
      const row = _rowsByKey.get(key);
      _syncColumnCounts(kanbanEl);
      if (!key || !newStatus || !row) return;
      el.classList.add('ops-card-staged');
      try {
        const saved = await _postStage(key, { status: newStatus }, row.updated_at || null);
        if (!_stagedByKey.has(key)) _stagedByKey.set(key, []);
        _stagedByKey.get(key).push(saved);
        _syncViewBadge();
      } catch (err) {
        console.warn('Operations: stage failed', err);
        el.title = 'Stage failed — ' + err.message;
      }
    },
  });

  _wireNoteButtons(kanbanEl);
  rows.forEach((r) => _renderNotesFor(r.key, kanbanEl));
}

// ---------------------------------------------------------------------------
// Table (primary view) — filters + desktop table + mobile cards.
// ---------------------------------------------------------------------------

// One filter axis rendered as a toggle button + a checkbox-list popover —
// replaces the old always-visible chip row. `_openFilterDim` (module state)
// decides which single dropdown, if any, is expanded; it survives the
// re-render a checkbox click triggers so picking several values in a row
// doesn't close the panel.
function _filterDropdownHtml(dim, label, values, valueLabel, filterSet, countFor) {
  const activeCount = filterSet.size;
  const open = _openFilterDim === dim;
  return `
    <div class="ops-filter-dropdown">
      <button type="button" class="ops-filter-toggle${activeCount ? ' active' : ''}" data-toggle-dim="${dim}">
        ${_esc(label)}${activeCount ? ` (${activeCount})` : ''} <span class="ops-filter-caret">${open ? '▴' : '▾'}</span>
      </button>
      ${open ? `<div class="ops-filter-panel">
        ${values.map((v) => `
          <label class="ops-filter-option">
            <input type="checkbox" data-dim="${dim}" data-val="${_esc(v)}" ${filterSet.has(v) ? 'checked' : ''} />
            <span>${_esc(valueLabel(v))}</span>
            <span class="ops-chip-count">(${countFor(v)})</span>
          </label>`).join('')}
      </div>` : ''}
    </div>`;
}

function _filtersHtml(pool) {
  const countingBase = {
    status: _matchingExcept(pool, 'status'),
    flags: _matchingExcept(pool, 'flags'),
    source: _matchingExcept(pool, 'source'),
    operator: _matchingExcept(pool, 'operator'),
  };
  const countFor = (dim, value) => {
    if (dim === 'status') return countingBase.status.filter((r) => r.status === value).length;
    if (dim === 'flags') return countingBase.flags.filter((r) => _hasFlag(r, value)).length;
    if (dim === 'source') return countingBase.source.filter((r) => r.source === value).length;
    return countingBase.operator.filter((r) => r.operator === value).length;
  };
  const operators = [...new Set(pool.map((r) => r.operator).filter(Boolean))].sort();
  const openActive = OPEN_STATUSES.length === _statusFilter.size && OPEN_STATUSES.every((s) => _statusFilter.has(s));
  const anyActive = _statusFilter.size || _flagFilter.size || _sourceFilter.size || _operatorFilter.size || _search;

  return `
    <div class="ops-filters">
      <div class="ops-filters-row1">
        <button type="button" class="ops-chip${openActive ? ' active' : ''}" data-open-preset="1">Open</button>
        ${_filterDropdownHtml('status', 'Status', STATUSES, (v) => v, _statusFilter, (v) => countFor('status', v))}
        ${_filterDropdownHtml('flags', 'Flags', FLAGS, (v) => FLAG_LABELS[v], _flagFilter, (v) => countFor('flags', v))}
        ${_filterDropdownHtml('source', 'Source', SOURCES, (v) => SOURCE_LABELS[v], _sourceFilter, (v) => countFor('source', v))}
        ${operators.length ? _filterDropdownHtml('operator', 'Operator', operators, (v) => v, _operatorFilter, (v) => countFor('operator', v)) : ''}
      </div>
      <div class="ops-filters-row2">
        <input type="text" class="ops-search-input" placeholder="Search name, email, phone, operator…" value="${_esc(_search)}" />
        <button type="button" class="ops-chip${_spamOnly ? ' active' : ''}" id="ops-spam-toggle">Spam</button>
        ${anyActive ? '<button type="button" class="ops-clear-filters">Clear filters</button>' : ''}
      </div>
    </div>`;
}

function _rowSummaryLine(row) {
  const summary = (row.summary || []).join(' · ');
  return summary ? `<div class="ops-summary-chip">${_esc(summary)}</div>` : '';
}

function _renderTable(body) {
  const pool = _visiblePool();
  const rows = _matchingExcept(pool, null);

  body.innerHTML = `
    <div class="ops-table-view">
      ${_filtersHtml(pool)}
      <div class="ops-bulk-bar" style="display:${_selectedKeys.size ? 'flex' : 'none'}">
        <span>${_selectedKeys.size} selected</span>
        <button type="button" class="ops-chip" id="ops-bulk-spam">Mark as spam</button>
        <button type="button" class="ops-chip" id="ops-bulk-clear">Clear</button>
      </div>
      <div class="ops-table-scroll">
        <div class="ops-table-desktop">
          <table class="ops-table">
            <thead><tr>
              <th style="width:26px;"><input type="checkbox" id="ops-select-all" ${rows.length && rows.every((r) => _selectedKeys.has(r.key)) ? 'checked' : ''}></th>
              <th>Source</th><th>Request</th><th>Operator</th><th>Due</th><th>Status</th>
            </tr></thead>
            <tbody id="ops-table-body"></tbody>
          </table>
        </div>
        <div class="ops-table-mobile" id="ops-mobile-body"></div>
      </div>
    </div>`;

  const tbody = body.querySelector('#ops-table-body');
  const mobile = body.querySelector('#ops-mobile-body');

  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--fg-muted,#888);">No requests match these filters.</td></tr>`;
  }

  rows.forEach((row) => {
    const eff = _effectiveRow(row);
    const overdue = _isOverdue(row);
    const age = _ageInDays(row.created_at);
    const risk = row.risk === 'suspected' ? '<span class="ops-risk ops-risk-suspected" title="Suspected spam"></span>' : '';
    const contact = [row.name, row.email, row.phone].filter(Boolean).join(' · ');

    const tr = document.createElement('tr');
    tr.className = 'ops-row';
    tr.dataset.key = row.key;
    tr.innerHTML = `
      <td><input type="checkbox" class="ops-row-select" ${_selectedKeys.has(row.key) ? 'checked' : ''}></td>
      <td><span class="ops-status-badge">${_esc(SOURCE_LABELS[row.source] || row.source)}</span> ${risk}</td>
      <td>
        <div class="ops-card-title">${_esc(row.name || row.email || row.key)}</div>
        ${contact ? `<div class="ops-card-contact">${_esc(contact)}</div>` : ''}
        ${_rowSummaryLine(row)}
      </td>
      <td>${_esc(eff.operator || 'Unassigned')}</td>
      <td>${eff.next_action_date ? _esc(eff.next_action_date) : '<span style="opacity:.5">No date</span>'}${age !== null ? `<div class="ops-card-meta">${age}d old</div>` : ''}${overdue ? '<div class="ops-card-meta" style="color:var(--accent,#e8a33d)">OVERDUE</div>' : ''}</td>
      <td><span class="ops-status-badge">${_esc(eff.status)}</span></td>
    `;
    tbody.appendChild(tr);

    const card = document.createElement('div');
    card.className = 'ops-mobile-card';
    card.dataset.key = row.key;
    card.innerHTML = `
      <div class="ops-mobile-card-head">
        <div>
          <div class="ops-card-title">${risk}${_esc(row.name || row.email || row.key)}</div>
          <div class="ops-card-contact">${_esc(contact)}</div>
          ${_rowSummaryLine(row)}
        </div>
        <span class="ops-status-badge">${_esc(eff.status)}</span>
      </div>`;
    mobile.appendChild(card);
  });

  // Row click (outside the checkbox) expands the shared editor — appended
  // as an extra table row / extra card content, not a navigation.
  function toggleExpand(key, host, isTable) {
    const already = host.querySelector(`[data-expanded-for="${CSS.escape(key)}"]`);
    if (already) { already.remove(); return; }
    host.querySelectorAll('[data-expanded-for]').forEach((el) => el.remove());
    const row = _rowsByKey.get(key);
    if (!row) return;
    if (isTable) {
      const tr = document.createElement('tr');
      tr.dataset.expandedFor = key;
      const td = document.createElement('td');
      td.colSpan = 6;
      td.className = 'ops-editor-cell';
      tr.appendChild(td);
      host.querySelector(`tr[data-key="${CSS.escape(key)}"]`).insertAdjacentElement('afterend', tr);
      _renderEditor(row, td);
    } else {
      const holder = document.createElement('div');
      holder.dataset.expandedFor = key;
      host.querySelector(`.ops-mobile-card[data-key="${CSS.escape(key)}"]`).appendChild(holder);
      _renderEditor(row, holder);
    }
  }

  tbody.querySelectorAll('tr.ops-row').forEach((tr) => {
    tr.addEventListener('click', (e) => {
      if (e.target.closest('.ops-row-select')) return;
      toggleExpand(tr.dataset.key, tbody, true);
    });
  });
  mobile.querySelectorAll('.ops-mobile-card').forEach((card) => {
    card.querySelector('.ops-mobile-card-head').addEventListener('click', () => toggleExpand(card.dataset.key, mobile, false));
  });

  // Selection
  tbody.querySelectorAll('.ops-row-select').forEach((cb) => {
    cb.addEventListener('change', (e) => {
      const key = e.target.closest('tr').dataset.key;
      if (e.target.checked) _selectedKeys.add(key); else _selectedKeys.delete(key);
      _renderTable(body);
    });
  });
  const selectAll = body.querySelector('#ops-select-all');
  if (selectAll) {
    selectAll.addEventListener('change', () => {
      if (selectAll.checked) rows.forEach((r) => _selectedKeys.add(r.key));
      else rows.forEach((r) => _selectedKeys.delete(r.key));
      _renderTable(body);
    });
  }

  // Bulk moderation — stages a moderation patch per selected row.
  const bulkSpam = body.querySelector('#ops-bulk-spam');
  if (bulkSpam) {
    bulkSpam.addEventListener('click', async () => {
      const keys = [..._selectedKeys];
      for (const key of keys) {
        const row = _rowsByKey.get(key);
        if (!row) continue;
        try {
          const saved = await _postStage(key, { moderation: 'spam' }, row.updated_at || null);
          if (!_stagedByKey.has(key)) _stagedByKey.set(key, []);
          _stagedByKey.get(key).push(saved);
        } catch (err) {
          console.warn('Operations: bulk stage failed for', key, err);
        }
      }
      _selectedKeys = new Set();
      _syncViewBadge();
      _renderTable(body);
    });
  }
  const bulkClear = body.querySelector('#ops-bulk-clear');
  if (bulkClear) bulkClear.addEventListener('click', () => { _selectedKeys = new Set(); _renderTable(body); });

  // Filter dropdown wiring — one open panel at a time (_openFilterDim),
  // reopened automatically after the re-render a checkbox click triggers.
  if (_filterCloseHandler) { document.removeEventListener('click', _filterCloseHandler); _filterCloseHandler = null; }
  body.querySelectorAll('.ops-filter-toggle').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const dim = btn.dataset.toggleDim;
      _openFilterDim = _openFilterDim === dim ? null : dim;
      _renderTable(body);
    });
  });
  body.querySelectorAll('.ops-filter-panel input[type="checkbox"]').forEach((cb) => {
    cb.addEventListener('change', () => {
      const dim = cb.dataset.dim, val = cb.dataset.val;
      const set = dim === 'status' ? _statusFilter : dim === 'flags' ? _flagFilter : dim === 'source' ? _sourceFilter : _operatorFilter;
      if (set.has(val)) set.delete(val); else set.add(val);
      _selectedKeys = new Set();
      _renderTable(body);
    });
  });
  if (_openFilterDim) {
    _filterCloseHandler = (e) => {
      if (e.target.closest('.ops-filter-dropdown')) return;
      _openFilterDim = null;
      document.removeEventListener('click', _filterCloseHandler);
      _filterCloseHandler = null;
      _renderTable(body);
    };
    document.addEventListener('click', _filterCloseHandler);
  }
  const openPreset = body.querySelector('[data-open-preset]');
  if (openPreset) {
    openPreset.addEventListener('click', () => {
      const isActive = OPEN_STATUSES.length === _statusFilter.size && OPEN_STATUSES.every((s) => _statusFilter.has(s));
      _statusFilter = isActive ? new Set() : new Set(OPEN_STATUSES);
      _renderTable(body);
    });
  }
  const spamToggle = body.querySelector('#ops-spam-toggle');
  if (spamToggle) spamToggle.addEventListener('click', () => { _spamOnly = !_spamOnly; _selectedKeys = new Set(); _renderTable(body); });
  const clearBtn = body.querySelector('.ops-clear-filters');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      _statusFilter = new Set(); _flagFilter = new Set(); _sourceFilter = new Set(); _operatorFilter = new Set(); _search = '';
      _renderTable(body);
    });
  }
  const searchInput = body.querySelector('.ops-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      _search = e.target.value;
      _selectedKeys = new Set();
      _renderTable(body);
    });
    // Re-focus + restore cursor after the re-render triggered by typing.
    searchInput.focus();
    const pos = searchInput.value.length;
    searchInput.setSelectionRange(pos, pos);
  }

  const tableWrap = body.querySelector('.ops-table-desktop, .ops-table-mobile');
  if (tableWrap) _wireNoteButtons(tableWrap.parentElement);
  rows.forEach((r) => _renderNotesFor(r.key, body));
}

// ---------------------------------------------------------------------------
// Push view
// ---------------------------------------------------------------------------

function _renderPush(body) {
  const items = [];
  for (const [key, list] of _stagedByKey.entries()) {
    for (const s of list) items.push({ ...s, key });
  }
  items.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));

  if (items.length === 0) {
    body.innerHTML = '<div class="ops-push-view"><div class="ops-push-empty">Nothing staged. Edit a request in Board or Table to stage a change here.</div></div>';
    return;
  }

  body.innerHTML = `
    <div class="ops-push-view">
      <div class="ops-push-toolbar">
        <button type="button" class="ops-chip ops-editor-save" id="ops-push-btn">Push ${items.length} change${items.length === 1 ? '' : 's'} to Supabase</button>
        <span class="ops-editor-hint" id="ops-push-result"></span>
      </div>
      <div id="ops-push-list"></div>
    </div>`;

  const list = body.querySelector('#ops-push-list');
  items.forEach((item) => {
    const row = _rowsByKey.get(item.key);
    const patchText = Object.entries(item.patch)
      .map(([field, value]) => `${PATCH_FIELD_LABELS[field] || field} → ${value ?? 'cleared'}`)
      .join(', ');
    const el = document.createElement('div');
    el.className = 'ops-push-item' + (item.conflict ? ' ops-conflict' : '');
    el.innerHTML = `
      <div class="ops-push-item-head">
        <div>
          <div class="ops-card-title">${_esc(row ? (row.name || row.email || item.key) : item.key)}</div>
          <div class="ops-card-meta">${_esc(patchText)}</div>
          ${item.rationale ? `<div class="ops-card-meta">${_esc(item.rationale)}</div>` : ''}
          <div class="ops-card-meta">${_esc(item.author)}${item.conflict ? ' — CONFLICT: this row changed since staging. Discard and re-stage from fresh data.' : ''}</div>
        </div>
        <button type="button" class="ops-chip ops-discard-staged" data-id="${_esc(item.id)}">Discard</button>
      </div>`;
    list.appendChild(el);
  });

  list.querySelectorAll('.ops-discard-staged').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        await _deleteStaged(btn.dataset.id);
        for (const [key, arr] of _stagedByKey.entries()) {
          const next = arr.filter((s) => s.id !== btn.dataset.id);
          if (next.length) _stagedByKey.set(key, next); else _stagedByKey.delete(key);
        }
        _syncViewBadge();
        _renderPush(body);
      } catch (err) {
        console.warn('Operations: discard failed', err);
      }
    });
  });

  body.querySelector('#ops-push-btn').addEventListener('click', async () => {
    const resultEl = body.querySelector('#ops-push-result');
    resultEl.textContent = 'Pushing…';
    try {
      const result = await _postPush();
      resultEl.textContent = `Pushed ${result.pushed.length}, conflicted ${result.conflicted.length}, failed ${result.failed.length}.`;
      // Refetch staged (pushed items are gone server-side; conflicted ones
      // now carry conflict=true) rather than reconstruct the diff locally.
      _stagedByKey = await _fetchStaged();
      _syncViewBadge();
      _renderPush(body);
    } catch (err) {
      resultEl.textContent = err.message;
    }
  });
}

// ---------------------------------------------------------------------------
// Modal shell
// ---------------------------------------------------------------------------

function _getModal() {
  if (_modal) return _modal;
  _injectStyles();
  _modal = document.createElement('div');
  _modal.id = 'operations-modal';
  _modal.className = 'modal';
  _modal.style.display = 'none';
  _modal.innerHTML = `
    <div class="modal-content ops-modal-content">
      <div class="modal-header">
        <h4><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px"><rect x="3" y="4" width="5" height="16" rx="1"/><rect x="9.5" y="4" width="5" height="10" rx="1"/><rect x="16" y="4" width="5" height="13" rx="1"/></svg>Operations</h4>
        <div class="ops-view-toggle">
          <button type="button" class="ops-view-btn" data-view="board">Board</button>
          <button type="button" class="ops-view-btn active" data-view="table">Table</button>
          <button type="button" class="ops-view-btn" data-view="push">Push</button>
        </div>
        <button class="close-btn" id="ops-close">✖</button>
      </div>
      <div class="modal-body"><div id="ops-body"></div></div>
    </div>`;
  document.body.appendChild(_modal);
  _modal.querySelectorAll('.ops-view-btn').forEach((b) => b.classList.toggle('active', b.dataset.view === _viewMode));
  _modal.querySelector('#ops-close').addEventListener('click', closeOperations);
  _modal.addEventListener('click', (e) => { if (e.target === _modal) closeOperations(); });
  _modal.querySelectorAll('.ops-view-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      _viewMode = btn.dataset.view;
      _modal.querySelectorAll('.ops-view-btn').forEach((b) => b.classList.toggle('active', b === btn));
      _renderCurrentView();
    });
  });
  const content = _modal.querySelector('.modal-content');
  const header = _modal.querySelector('.modal-header');
  if (content && header) makeWindowDraggable(_modal, { content, header });
  return _modal;
}

export function openOperations() {
  if (_open) return;
  if (Modals.isMinimized('operations-modal')) {
    Modals.restore('operations-modal');
    _open = true;
    return;
  }
  _open = true;
  const modal = _getModal();
  modal.classList.remove('hidden', 'modal-minimized');
  modal.style.display = 'flex';
  Modals.register('operations-modal', {
    railBtnId: 'rail-operations',
    sidebarBtnId: 'tool-operations-btn',
    closeFn: () => _doClose(),
    restoreFn: () => {},
  });
  _render();
}

function _doClose() {
  Modals.unregister('operations-modal');
  if (_modal) _modal.remove();
  _modal = null;
  _open = false;
  _lastRows = null;
  _notesByKey = new Map();
  _stagedByKey = new Map();
  _selectedKeys = new Set();
  _search = '';
  _openFilterDim = null;
  if (_filterCloseHandler) { document.removeEventListener('click', _filterCloseHandler); _filterCloseHandler = null; }
}

export function closeOperations() {
  _doClose();
}

export function isOperationsOpen() {
  return _open;
}

export default { openOperations, closeOperations, isOperationsOpen };
