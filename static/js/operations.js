// static/js/operations.js
//
// Human-viewable panel over the Bil Weekend operations worklist — the same
// data mcp_servers/ops_server.py exposes to agents. Talks to
// routes/operations/operations_routes.py, which proxies the same Bil Weekend
// endpoints the agent tools use, so there is exactly one worklist and one
// approval gate (Bil Weekend's own propose_change review), whether a change
// comes from an agent or a drag in this panel.
//
// Board columns are the worklist's own status values. Dragging a card
// between columns submits a status-change proposal — it does not apply
// immediately, since Bil Weekend's own admin still approves it. The card is
// marked pending until the next refresh confirms the real state.
//
// jKanban (Apache-2.0, vendored at /static/lib/jkanban.min.js, bundles
// Dragula for drag/drop) supplies the column/drag chrome. Loaded on first
// open rather than eagerly, matching how markdown.js lazy-loads Mermaid/KaTeX.

import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';

const JKANBAN_JS = '/static/lib/jkanban.min.js';
const JKANBAN_CSS = '/static/lib/jkanban.min.css';

const STATUSES = ['New', 'In Progress', 'Replied', 'On Hold', 'Confirmed', 'Rejected'];
// jKanban board ids can't safely carry spaces; slug for the DOM, map back for the API.
const STATUS_SLUG = Object.fromEntries(STATUSES.map((s) => [s, s.toLowerCase().replace(/\s+/g, '-')]));
const SLUG_STATUS = Object.fromEntries(STATUSES.map((s) => [s.toLowerCase().replace(/\s+/g, '-'), s]));
// Replied requests are the bulk of the worklist and rarely need attention —
// hidden from both views by default. Not user-configurable yet; that's the
// obvious next step if one hidden status isn't enough.
const HIDDEN_STATUSES = new Set(['Replied']);
const VISIBLE_STATUSES = STATUSES.filter((s) => !HIDDEN_STATUSES.has(s));

let _open = false;
let _modal = null;
let _rowsByKey = new Map(); // worklist key -> row, for expectedUpdatedAt on drop
let _lastRows = null; // last successful fetch — reused when switching Board/List so that doesn't refetch
let _notesByKey = new Map(); // worklist key -> note[], fetched once per open (was: one GET per row)
let _viewMode = 'board'; // 'board' | 'list'
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
    link.addEventListener('error', () => resolve(), { once: true }); // unstyled beats not-loaded
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
    /* overflow:hidden here (both axes, one declaration) overrides the base
       .modal-content rule (overflow-y:auto only) — that partial rule made
       the browser treat overflow-x as auto too (CSS overflow interop:
       "visible" on one axis becomes "auto" when the other isn't visible),
       giving .modal-content a competing scroll boundary above #ops-kanban's
       own and clipping the 5th column with no scrollbar ever rendering. */
    #operations-modal .ops-modal-content { width: min(1100px, 92vw); height: min(680px, 86vh); display: flex; flex-direction: column; overflow: hidden; }
    #operations-modal .modal-body { flex: 1; overflow: hidden; padding: 0; }
    #operations-modal #ops-body { height: 100%; display: flex; flex-direction: column; }
    #operations-modal .ops-loading, #operations-modal .ops-error { padding: 24px; color: var(--fg-muted, #888); }
    #operations-modal .ops-error { color: var(--color-danger, var(--accent-error, #d33)); }
    #operations-modal #ops-kanban.kanban-container { flex: 1; min-height: 0; overflow-x: auto; overflow-y: hidden; white-space: nowrap; padding: 12px; background: var(--bg, #1a1a1a); }
    /* jkanban.min.css floats boards left; a float wraps to a new line once it
       runs out of room instead of overflowing, so the container never scrolls.
       inline-flex (inline-level, like inline-block) respects nowrap on the
       parent, and lets each board be a column flex box internally so its
       header stays put while .kanban-drag scrolls on its own below. */
    #operations-modal .kanban-board { display: inline-flex; flex-direction: column; float: none; width: 260px; height: 100%; margin-right: 12px; border-radius: 8px; background: var(--bg-elev, #242424); border: 1px solid var(--border, #333); vertical-align: top; white-space: normal; }
    #operations-modal .ops-view-toggle { display: flex; gap: 4px; margin-left: auto; margin-right: 12px; }
    #operations-modal .ops-view-btn { background: var(--bg-elev, #242424); border: 1px solid var(--border, #333); color: var(--fg-muted, #888); border-radius: 6px; font-size: 11px; padding: 4px 10px; cursor: pointer; }
    #operations-modal .ops-view-btn.active { color: var(--fg, #eee); border-color: var(--accent, #e8a33d); }
    #operations-modal #ops-list { flex: 1; min-height: 0; overflow: auto; padding: 12px; }
    #operations-modal .ops-list-table { width: 100%; border-collapse: collapse; font-size: 12px; color: var(--fg, #eee); }
    #operations-modal .ops-list-table th { text-align: left; color: var(--fg-muted, #888); font-weight: 600; padding: 6px 8px; border-bottom: 1px solid var(--border, #333); position: sticky; top: 0; background: var(--bg, #1a1a1a); }
    #operations-modal .ops-list-table td { padding: 6px 8px; border-bottom: 1px solid var(--border, #333); vertical-align: top; }
    #operations-modal .kanban-board header { border-bottom: 1px solid var(--border, #333); flex-shrink: 0; }
    #operations-modal .kanban-title-board { color: var(--fg, #eee); font-size: 13px; }
    #operations-modal .ops-col-count { color: var(--fg-muted, #888); font-weight: 400; margin-left: 4px; }
    /* The scrollable part of each column — bug was #ops-kanban's own
       overflow-y:hidden (correct, the row of boards must not grow taller
       than the modal) with nothing giving the column itself anywhere to
       scroll internally. flex:1 + min-height:0 + overflow-y:auto here fixes
       that per-column, independent of the sibling columns' heights. */
    #operations-modal .kanban-drag { flex: 1; min-height: 0; overflow-y: auto; }
    #operations-modal .kanban-item { background: var(--bg, #1a1a1a); border: 1px solid var(--border, #333); border-radius: 6px; color: var(--fg, #eee); font-size: 12px; white-space: normal; }
    #operations-modal .ops-card-title { font-weight: 600; margin-bottom: 4px; }
    #operations-modal .ops-card-contact { color: var(--fg-dim, #aaa); font-size: 11px; margin-bottom: 4px; }
    #operations-modal .ops-card-meta { color: var(--fg-muted, #888); font-size: 11px; }
    #operations-modal .ops-card-notes { margin-top: 6px; border-top: 1px dashed var(--border, #333); padding-top: 6px; }
    #operations-modal .ops-card-note { font-size: 11px; color: var(--fg-dim, #aaa); margin-bottom: 3px; }
    #operations-modal .ops-card-note b { color: var(--fg, #eee); }
    #operations-modal .kanban-item.ops-card-pending { opacity: 0.6; border-style: dashed; }
    #operations-modal .kanban-item.ops-card-pending::after { content: 'pending approval'; display: block; margin-top: 6px; font-size: 10px; color: var(--accent, #e8a33d); }
    #operations-modal .ops-note-editor { margin-top: 6px; }
    #operations-modal .ops-note-editor textarea { width: 100%; box-sizing: border-box; background: var(--bg, #1a1a1a); color: var(--fg, #eee); border: 1px solid var(--border, #333); border-radius: 4px; font: inherit; font-size: 11px; padding: 4px; resize: vertical; }
    #operations-modal .ops-note-editor-actions { display: flex; gap: 6px; margin-top: 4px; }
    #operations-modal .ops-note-editor-actions button { font-size: 11px; padding: 2px 8px; border-radius: 4px; border: 1px solid var(--border, #333); background: var(--bg-elev, #242424); color: var(--fg, #eee); cursor: pointer; }
    #operations-modal .ops-note-save { border-color: var(--accent, #e8a33d); }
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
  // Field/wrapper names come from Bil Weekend's own API, which this module
  // hasn't been exercised against live — fall back across the plausible
  // shapes rather than assuming one, so a mismatch shows an empty board
  // instead of throwing.
  return data.items || data.rows || data.worklist || (Array.isArray(data) ? data : []);
}

// One call for every note, grouped client-side — replaces what used to be
// one GET per visible row (61 concurrent requests on a 61-row worklist).
// The backend already supports this: `key` on GET /api/operations/notes is
// optional, and omitting it returns every note.
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

async function _postStatus(key, status, expectedUpdatedAt) {
  const res = await fetch('/api/operations/status', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, status, expectedUpdatedAt }),
  });
  if (!res.ok) throw await _errorFromResponse(res, 'Failed to submit status change');
  return res.json();
}

function _cardHtml(row) {
  const title = row.summary || row.name || row.email || row.key;
  const contact = [row.name, row.email, row.phone].filter(Boolean).join(' · ');
  const meta = [row.operator, row.overdue ? 'OVERDUE' : null].filter(Boolean).join(' · ');
  return (
    `<div class="ops-card-title">${_esc(title)}</div>` +
    (contact ? `<div class="ops-card-contact">${_esc(contact)}</div>` : '') +
    (meta ? `<div class="ops-card-meta">${_esc(meta)}</div>` : '') +
    `<div class="ops-card-notes" data-notes-for="${_esc(row.key)}"></div>` +
    `<button type="button" class="ops-card-add-note" data-note-key="${_esc(row.key)}" style="margin-top:6px;font-size:11px;">+ note</button>`
  );
}

function _wireNoteButtons(container) {
  container.querySelectorAll('.ops-card-add-note').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      _openNoteEditor(btn, container);
    });
  });
}

// Inline textarea + Save/Cancel, replacing window.prompt(): a native prompt
// is a blocking, unstyled modal dialog with no multi-line support — a real
// UX defect independent of anything else.
function _openNoteEditor(btn, container) {
  if (btn.nextElementSibling && btn.nextElementSibling.classList.contains('ops-note-editor')) return;
  const key = btn.dataset.noteKey;
  const editor = document.createElement('div');
  editor.className = 'ops-note-editor';
  editor.innerHTML = `
    <textarea rows="2" placeholder="Note…"></textarea>
    <div class="ops-note-editor-actions">
      <button type="button" class="ops-note-save">Save</button>
      <button type="button" class="ops-note-cancel">Cancel</button>
    </div>`;
  editor.addEventListener('click', (e) => e.stopPropagation()); // don't start a card drag
  btn.insertAdjacentElement('afterend', editor);
  btn.style.display = 'none';
  const textarea = editor.querySelector('textarea');
  textarea.focus();

  const close = () => { editor.remove(); btn.style.display = ''; };
  editor.querySelector('.ops-note-cancel').addEventListener('click', close);
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
  slot.innerHTML = notes
    .slice(0, 5)
    .map((n) => `<div class="ops-card-note"><b>${_esc(n.author)}:</b> ${_esc(n.text)}</div>`)
    .join('');
}

function _markPending(el) {
  el.classList.add('ops-card-pending');
}

// Recompute each column's header count from what's actually in its
// .kanban-drag right now. Needed because Dragula moves the card's DOM node
// on drop before dropEl fires — the header counts (static text set at
// board-build time) go stale the instant a drag completes, regardless of
// whether the follow-up status-change request succeeds.
function _syncColumnCounts(kanbanEl) {
  kanbanEl.querySelectorAll('.kanban-board').forEach((board) => {
    const countEl = board.querySelector('.ops-col-count');
    const drag = board.querySelector('.kanban-drag');
    if (countEl && drag) countEl.textContent = drag.querySelectorAll('.kanban-item').length;
  });
}

async function _render() {
  const body = _modal.querySelector('#ops-body');
  body.innerHTML = '<div class="ops-loading">Loading worklist…</div>';

  let rows, notesByKey;
  try {
    [rows, notesByKey] = await Promise.all([_fetchWorklist(), _fetchAllNotes(), _ensureJKanban()]);
  } catch (err) {
    body.innerHTML = `<div class="ops-error">${_esc(err.message)}</div>`;
    return;
  }

  _lastRows = rows;
  _notesByKey = notesByKey;
  _rowsByKey = new Map(rows.map((r) => [r.key, r]));
  _renderCurrentView();
}

// Switching Board/List re-renders from _lastRows — no network round trip,
// since neither view mode nor the Replied filter change what's on the server.
function _renderCurrentView() {
  if (!_modal || !_lastRows) return;
  const body = _modal.querySelector('#ops-body');
  const rows = _lastRows.filter((r) => !HIDDEN_STATUSES.has(r.status));
  if (_viewMode === 'list') _renderList(rows, body);
  else _renderBoard(rows, body);
}

function _renderBoard(rows, body) {
  body.innerHTML = '<div id="ops-kanban"></div>';
  const kanbanEl = body.querySelector('#ops-kanban');

  const boards = VISIBLE_STATUSES.map((status) => {
    const rowsInStatus = rows.filter((r) => r.status === status);
    return {
      id: STATUS_SLUG[status],
      title: `${_esc(status)} <span class="ops-col-count">${rowsInStatus.length}</span>`,
      item: rowsInStatus.map((r) => ({ id: r.key, title: _cardHtml(r) })),
    };
  });

  new window.jKanban({
    element: '#ops-kanban',
    boards,
    dropEl: async (el, target) => {
      // jKanban's dropEl hands over Dragula's raw drop target, which is the
      // .kanban-drag item-list div — the board id set via boards[].id lives
      // as data-id on ITS PARENT (.kanban-board), confirmed by reading
      // jkanban.min.js's own drop handler (`n.parentNode.dataset.id`).
      // target.dataset.id is always undefined; this silently no-opped every
      // drag (no request, no pending state, no error — just a DOM move).
      const key = el.dataset.eid;
      const newStatus = SLUG_STATUS[target.parentNode?.dataset.id];
      const row = _rowsByKey.get(key);
      _syncColumnCounts(kanbanEl); // Dragula already moved the DOM node; counts are stale either way
      if (!key || !newStatus || !row) {
        console.warn('Operations: drop ignored — could not resolve key/status/row', { key, newStatus, row });
        return;
      }
      _markPending(el);
      try {
        await _postStatus(key, newStatus, row.updatedAt || row.updated_at || null);
      } catch (err) {
        console.warn('Operations: status change failed', err);
        el.title = 'Submit failed — refresh to see the real state';
      }
    },
  });

  _wireNoteButtons(kanbanEl);
  rows.forEach((r) => _renderNotesFor(r.key, kanbanEl));
}

// Table view — same data as the board, laid out the way Bil Weekend's own
// "All Requests" admin view does (a flat list, not a spatial board), but not
// a clone of it: no per-source-type columns, no built-in sort/filter chrome.
function _renderList(rows, body) {
  body.innerHTML = '<div id="ops-list"></div>';
  const el = body.querySelector('#ops-list');
  const table = document.createElement('table');
  table.className = 'ops-list-table';
  table.innerHTML = `
    <thead><tr><th>Status</th><th>Request</th><th>Operator</th><th>Updated</th><th>Notes</th></tr></thead>
    <tbody>
      ${rows.map((r) => {
        const contact = [r.name, r.email, r.phone].filter(Boolean).join(' · ');
        return `
        <tr>
          <td>${_esc(r.status)}</td>
          <td>
            <div class="ops-card-title">${_esc(r.summary || r.name || r.email || r.key)}</div>
            ${contact ? `<div class="ops-card-contact">${_esc(contact)}</div>` : ''}
          </td>
          <td>${_esc(r.operator || '—')}</td>
          <td>${_esc((r.updated_at || '').slice(0, 10) || '—')}</td>
          <td>
            <div class="ops-card-notes" data-notes-for="${_esc(r.key)}"></div>
            <button type="button" class="ops-card-add-note" data-note-key="${_esc(r.key)}">+ note</button>
          </td>
        </tr>`;
      }).join('')}
    </tbody>`;
  el.appendChild(table);
  _wireNoteButtons(el);
  rows.forEach((r) => _renderNotesFor(r.key, el));
}

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
          <button type="button" class="ops-view-btn active" data-view="board">Board</button>
          <button type="button" class="ops-view-btn" data-view="list">List</button>
        </div>
        <button class="close-btn" id="ops-close">✖</button>
      </div>
      <div class="modal-body"><div id="ops-body"></div></div>
    </div>`;
  document.body.appendChild(_modal);
  // The template above hardcodes "Board" active; _viewMode persists across a
  // close (only _lastRows/_notesByKey reset), so without this a reopen after
  // switching to List renders the List content under a "Board" that still
  // looks selected.
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
  // Unregistering here is load-bearing: without it, ModalManager keeps this
  // id registered against a DOM node that's about to be removed. The next
  // click calls Modals.toggle('operations-modal'), which finds the stale
  // registration and tries to restore/minimize a modal that no longer
  // exists instead of returning false — so openOperations() never runs and
  // the first click after a close silently does nothing.
  Modals.unregister('operations-modal');
  if (_modal) _modal.remove();
  _modal = null;
  _open = false;
  _lastRows = null; // next open fetches fresh rather than showing stale data
  _notesByKey = new Map();
}

export function closeOperations() {
  _doClose();
}

export function isOperationsOpen() {
  return _open;
}

export default { openOperations, closeOperations, isOperationsOpen };
