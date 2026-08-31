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
    #operations-modal .ops-modal-content { width: min(1100px, 92vw); height: min(680px, 86vh); display: flex; flex-direction: column; }
    #operations-modal .modal-body { flex: 1; overflow: hidden; padding: 0; }
    #operations-modal #ops-body { height: 100%; display: flex; flex-direction: column; }
    #operations-modal .ops-loading, #operations-modal .ops-error { padding: 24px; color: var(--fg-muted, #888); }
    #operations-modal .ops-error { color: var(--color-danger, var(--accent-error, #d33)); }
    #operations-modal #ops-kanban.kanban-container { flex: 1; min-height: 0; overflow-x: auto; overflow-y: hidden; white-space: nowrap; padding: 12px; background: var(--bg, #1a1a1a); }
    /* jkanban.min.css floats boards left; a float wraps to a new line once it
       runs out of room instead of overflowing, so the container never scrolls.
       inline-block boxes respect white-space:nowrap on their container instead. */
    #operations-modal .kanban-board { display: inline-block; float: none; width: 260px; margin-right: 12px; border-radius: 8px; background: var(--bg-elev, #242424); border: 1px solid var(--border, #333); vertical-align: top; white-space: normal; }
    #operations-modal .ops-view-toggle { display: flex; gap: 4px; margin-left: auto; margin-right: 12px; }
    #operations-modal .ops-view-btn { background: var(--bg-elev, #242424); border: 1px solid var(--border, #333); color: var(--fg-muted, #888); border-radius: 6px; font-size: 11px; padding: 4px 10px; cursor: pointer; }
    #operations-modal .ops-view-btn.active { color: var(--fg, #eee); border-color: var(--accent, #e8a33d); }
    #operations-modal #ops-list { flex: 1; min-height: 0; overflow: auto; padding: 12px; }
    #operations-modal .ops-list-table { width: 100%; border-collapse: collapse; font-size: 12px; color: var(--fg, #eee); }
    #operations-modal .ops-list-table th { text-align: left; color: var(--fg-muted, #888); font-weight: 600; padding: 6px 8px; border-bottom: 1px solid var(--border, #333); position: sticky; top: 0; background: var(--bg, #1a1a1a); }
    #operations-modal .ops-list-table td { padding: 6px 8px; border-bottom: 1px solid var(--border, #333); vertical-align: top; }
    #operations-modal .kanban-board header { border-bottom: 1px solid var(--border, #333); }
    #operations-modal .kanban-title-board { color: var(--fg, #eee); font-size: 13px; }
    #operations-modal .ops-col-count { color: var(--fg-muted, #888); font-weight: 400; margin-left: 4px; }
    #operations-modal .kanban-drag { min-height: 120px; }
    #operations-modal .kanban-item { background: var(--bg, #1a1a1a); border: 1px solid var(--border, #333); border-radius: 6px; color: var(--fg, #eee); font-size: 12px; white-space: normal; }
    #operations-modal .ops-card-title { font-weight: 600; margin-bottom: 4px; }
    #operations-modal .ops-card-contact { color: var(--fg-dim, #aaa); font-size: 11px; margin-bottom: 4px; }
    #operations-modal .ops-card-meta { color: var(--fg-muted, #888); font-size: 11px; }
    #operations-modal .ops-card-notes { margin-top: 6px; border-top: 1px dashed var(--border, #333); padding-top: 6px; }
    #operations-modal .ops-card-note { font-size: 11px; color: var(--fg-dim, #aaa); margin-bottom: 3px; }
    #operations-modal .ops-card-note b { color: var(--fg, #eee); }
    #operations-modal .kanban-item.ops-card-pending { opacity: 0.6; border-style: dashed; }
    #operations-modal .kanban-item.ops-card-pending::after { content: 'pending approval'; display: block; margin-top: 6px; font-size: 10px; color: var(--accent, #e8a33d); }
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

async function _fetchNotes(key) {
  const res = await fetch('/api/operations/notes?key=' + encodeURIComponent(key), { credentials: 'same-origin' });
  if (!res.ok) return [];
  const data = await res.json();
  return data.notes || [];
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
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const key = btn.dataset.noteKey;
      const text = window.prompt('Note for ' + key + ':');
      if (!text) return;
      try {
        await _postNote(key, text);
        _renderNotesFor(key, container);
      } catch (err) {
        console.warn('Operations: note save failed', err);
      }
    });
  });
}

async function _renderNotesFor(key, container) {
  const slot = container.querySelector(`.ops-card-notes[data-notes-for="${CSS.escape(key)}"]`);
  if (!slot) return;
  const notes = await _fetchNotes(key);
  slot.innerHTML = notes
    .slice(0, 5)
    .map((n) => `<div class="ops-card-note"><b>${_esc(n.author)}:</b> ${_esc(n.text)}</div>`)
    .join('');
}

function _markPending(el) {
  el.classList.add('ops-card-pending');
}

async function _render() {
  const body = _modal.querySelector('#ops-body');
  body.innerHTML = '<div class="ops-loading">Loading worklist…</div>';

  let rows;
  try {
    [rows] = await Promise.all([_fetchWorklist(), _ensureJKanban()]);
  } catch (err) {
    body.innerHTML = `<div class="ops-error">${_esc(err.message)}</div>`;
    return;
  }

  _lastRows = rows;
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
      const key = el.dataset.eid;
      const newStatus = SLUG_STATUS[target.dataset.id];
      const row = _rowsByKey.get(key);
      if (!key || !newStatus || !row) return;
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
  if (_modal) _modal.remove();
  _modal = null;
  _open = false;
  _lastRows = null; // next open fetches fresh rather than showing stale data
}

export function closeOperations() {
  _doClose();
}

export function isOperationsOpen() {
  return _open;
}

export default { openOperations, closeOperations, isOperationsOpen };
