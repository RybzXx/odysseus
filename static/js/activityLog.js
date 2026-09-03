// static/js/activityLog.js
/**
 * Activity Log Module — Unified Observability & Audit Hub for Odysseus.
 * Displays all non-chat system queries, background jobs, tool executions, and model latencies.
 */

import { makeWindowDraggable } from './windowDrag.js';
import uiModule from './ui.js';
import markdownModule from './markdown.js';

// Inline Feather/Lucide SVG Icons (Zero Emojis)
//
// checkCircle, alertCircle and clock are byte-identical copies of overview.js's
// entries. Divergent redraws of the same glyph are exactly what a shared visual
// language cannot afford, and this repo's pattern is a per-module ICONS const
// rather than a shared module — so the copy must be exact.
const ICONS = {
  bolt: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  refresh: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>`,
  trash: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>`,
  close: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
  checkCircle: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>`,
  alertCircle: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
  clock: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
  // Two glyphs no other module needed yet, drawn to the same Feather
  // convention: 24x24 box, stroke-width 2, round caps and joins.
  alertTriangle: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
  stopCircle: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><rect x="9" y="9" width="6" height="6" rx="1"/></svg>`,
};

/**
 * The glyph for a log status.
 *
 * Pre:  `status` is one of the five values system_logger normalises to.
 * Post: a Feather glyph; an unrecognised status falls back to checkCircle
 *       rather than rendering nothing, so a row is never iconless.
 */
function _statusIcon(status) {
  switch (status) {
    case 'running': return ICONS.clock;
    case 'error': return ICONS.alertCircle;
    case 'fallback': return ICONS.alertTriangle;
    case 'halted': return ICONS.stopCircle;
    default: return ICONS.checkCircle;
  }
}

let _open = false;
let _modal = null;
let _logs = [];
let _stats = null;
let _currentModuleFilter = 'all';
let _currentStatusFilter = 'all';
let _searchQuery = '';
let _pollInterval = null;
let _expandedLogIds = new Set();
let _stylesInjected = false;

function _esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function _formatDate(isoStr) {
  if (!isoStr) return '—';
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' ' + d.toLocaleDateString();
  } catch {
    return isoStr;
  }
}

function _formatDuration(ms) {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function _injectStyles() {
  if (_stylesInjected) return;
  _stylesInjected = true;

  const style = document.createElement('style');
  style.id = 'activity-log-styles';
  style.textContent = `
    /* Own root class, not .modal. This panel already positions and sizes
       itself, which is the .overview-modal / .organisers-modal shape; it also
       carried the .modal class, whose base rule in style.css sets
       align-items:center. In a COLUMN flex container that shrink-wraps every
       child to max-content, and .act-preview-text is white-space:nowrap — so
       one long result string stretched the list to ~29,000px inside a 918px
       panel and every row rendered blank. Dropping the class removes the
       cause; align-items below states the intent rather than relying on it. */
    .activity-log-panel {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: min(920px, 94vw);
      height: min(720px, 86vh);
      background: var(--bg, #181a1f);
      color: var(--fg, #abb2bf);
      border: 1px solid var(--border, rgba(255,255,255,0.12));
      border-radius: 12px;
      box-shadow: 0 16px 48px rgba(0,0,0,0.5);
      z-index: 100060;
      display: flex;
      flex-direction: column;
      align-items: stretch;
      overflow: hidden;
      font-family: var(--font-family, system-ui, sans-serif);
    }
    .activity-log-panel.hidden { display: none !important; }

    .act-header {
      padding: 14px 18px;
      background: var(--panel, #21252b);
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
      display: flex;
      align-items: center;
      justify-content: space-between;
      user-select: none;
      cursor: move;
    }
    .act-title {
      font-size: 15px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 0;
    }
    .act-controls {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .act-btn {
      background: rgba(255,255,255,0.06);
      color: var(--fg, #abb2bf);
      border: 1px solid var(--border, rgba(255,255,255,0.1));
      border-radius: 6px;
      padding: 5px 10px;
      font-size: 12px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: background 0.15s ease, border-color 0.15s ease;
    }
    .act-btn:hover {
      background: rgba(255,255,255,0.12);
      border-color: var(--red, #e06c75);
      color: #fff;
    }
    .act-btn.danger:hover {
      background: rgba(224, 108, 117, 0.2);
      border-color: var(--red, #e06c75);
      color: #fff;
    }

    .act-stats-bar {
      padding: 8px 18px;
      background: rgba(0,0,0,0.2);
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
      display: flex;
      gap: 16px;
      font-size: 12px;
      align-items: center;
      flex-wrap: wrap;
    }
    .act-stat-item {
      display: flex;
      gap: 5px;
      align-items: center;
    }
    .act-stat-val {
      font-weight: 700;
      font-family: 'Fira Code', monospace;
      color: var(--fg, #fff);
    }

    .act-toolbar {
      padding: 10px 18px;
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .act-filter-chips {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
    }
    .act-chip {
      background: var(--panel, #21252b);
      color: var(--fg, #abb2bf);
      opacity: 0.75;
      border: 1px solid var(--border, rgba(255,255,255,0.1));
      border-radius: 20px;
      padding: 3px 10px;
      font-size: 11.5px;
      cursor: pointer;
      transition: background 0.15s ease, border-color 0.15s ease, opacity 0.15s ease;
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }
    .act-chip:hover {
      opacity: 1;
      color: #fff;
      border-color: rgba(255,255,255,0.2);
    }
    .act-chip.active {
      background: var(--red, #e06c75);
      color: #fff;
      border-color: var(--red, #e06c75);
      opacity: 1;
      font-weight: 600;
    }
    .act-chip-count {
      font-size: 10px;
      opacity: 0.8;
      background: rgba(0,0,0,0.25);
      padding: 1px 5px;
      border-radius: 10px;
    }

    .act-search-row {
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .act-search-input {
      flex: 1;
      min-width: 0;
      background: rgba(0,0,0,0.25);
      border: 1px solid var(--border, rgba(255,255,255,0.12));
      border-radius: 6px;
      padding: 6px 12px;
      font-size: 12.5px;
      color: var(--fg, #abb2bf);
    }
    .act-search-input:focus {
      outline: none;
      border-color: var(--red, #e06c75);
    }

    /* min-width:0 on both: a flex item defaults to min-width:auto, which
       refuses to shrink below its content. Without these the nowrap preview
       text below can still widen its ancestors past the panel. */
    .act-list-container {
      flex: 1;
      min-width: 0;
      overflow-y: auto;
      padding: 12px 18px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .act-row {
      min-width: 0;
      background: var(--panel, #21252b);
      border: 1px solid var(--border, rgba(255,255,255,0.08));
      border-radius: 8px;
      padding: 10px 14px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      transition: border-color 0.15s ease, background 0.15s ease;
      cursor: pointer;
    }
    .act-row:hover {
      border-color: rgba(255,255,255,0.2);
    }
    .act-row.expanded {
      border-color: var(--red, #e06c75);
      background: rgba(255,255,255,0.03);
    }

    .act-row-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-width: 0;
    }
    .act-row-left {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    /* Each status binds one colour; the badge shape is written once against
       it. The tokens are derived per theme by deriveStatusColors in theme.js,
       so these follow a theme switch instead of staying One Dark under all
       sixteen. The literals are the pre-token values, kept as the last rung
       of the cascade for a first paint with no stored theme. */
    .act-status-badge {
      font-size: 10px;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      flex-shrink: 0;
      background: color-mix(in srgb, var(--act-status) 18%, transparent);
      color: var(--act-status);
      border: 1px solid color-mix(in srgb, var(--act-status) 40%, transparent);
    }
    /* The glyphs are copied at their source size; the badge sets the size it
       needs rather than the copies being edited away from their originals. */
    .act-status-badge svg { width: 11px; height: 11px; }
    .act-status-completed { --act-status: var(--status-ok, #98c379); }
    .act-status-running   { --act-status: var(--status-busy, #61afef); }
    .act-status-error     { --act-status: var(--status-error, #e06c75); }
    .act-status-fallback  { --act-status: var(--status-warn, #d19a66); }
    .act-status-halted    { --act-status: var(--status-idle, #c678dd); }

    .act-module-tag {
      font-size: 10px;
      font-weight: 700;
      background: rgba(255, 255, 255, 0.08);
      color: var(--fg, #bbb);
      padding: 2px 6px;
      border-radius: 4px;
      text-transform: uppercase;
    }
    .act-target-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--fg, #fff);
    }
    .act-repeat-badge {
      font-size: 10px;
      font-weight: 700;
      background: #61afef;
      color: #fff;
      padding: 1px 5px;
      border-radius: 8px;
    }

    .act-row-right {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 11px;
      color: var(--fg, #abb2bf);
      opacity: 0.6;
      flex-shrink: 0;
    }
    .act-model-pill {
      font-family: 'Fira Code', monospace;
      font-size: 10.5px;
      background: rgba(0,0,0,0.3);
      padding: 2px 6px;
      border-radius: 4px;
      color: #61afef;
      border: 1px solid rgba(97, 175, 239, 0.3);
    }
    .act-latency-badge {
      font-family: 'Fira Code', monospace;
      font-size: 10.5px;
      color: #98c379;
    }

    .act-preview-text {
      min-width: 0;
      font-size: 12px;
      line-height: 1.4;
      color: var(--fg, #abb2bf);
      opacity: 0.85;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .act-detail-drawer {
      margin-top: 8px;
      padding-top: 10px;
      border-top: 1px solid var(--border, rgba(255,255,255,0.08));
      display: flex;
      flex-direction: column;
      gap: 10px;
      font-size: 12px;
      min-width: 0;
    }
    .act-detail-section {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .act-detail-label {
      font-size: 10.5px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--red, #e06c75);
    }
    .act-detail-box {
      background: rgba(0,0,0,0.35);
      border: 1px solid var(--border, rgba(255,255,255,0.08));
      border-radius: 6px;
      padding: 8px 12px;
      font-family: 'Fira Code', monospace;
      font-size: 11.5px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      max-height: 240px;
      overflow-y: auto;
      color: var(--fg, #abb2bf);
    }
  `;
  document.head.appendChild(style);
}

async function _fetchLogs() {
  try {
    const params = new URLSearchParams({
      limit: '100',
      module: _currentModuleFilter,
      status: _currentStatusFilter,
    });
    if (_searchQuery.trim()) {
      params.set('search', _searchQuery.trim());
    }

    const [logsRes, statsRes] = await Promise.all([
      fetch(`/api/system/activity-logs?${params.toString()}`),
      fetch('/api/system/activity-logs/stats'),
    ]);

    if (logsRes.ok) {
      const data = await logsRes.json();
      _logs = data.logs || [];
    }
    if (statsRes.ok) {
      _stats = await statsRes.json();
      _updateSidebarIndicator();
    }
    _render();
  } catch (err) {
    console.warn('[ActivityLog] fetch failed:', err);
  }
}

function _updateSidebarIndicator() {
  const dot = document.getElementById('activity-log-indicator');
  if (!dot) return;
  if (_stats && _stats.running_count > 0) {
    dot.style.display = 'inline-block';
    dot.title = `${_stats.running_count} system query running`;
  } else {
    dot.style.display = 'none';
  }
}

const MODULE_CHIPS = [
  { key: 'all', label: 'All' },
  { key: 'projects', label: 'Projects' },
  { key: 'tasks', label: 'Tasks' },
  { key: 'email', label: 'Email' },
  { key: 'operations', label: 'Operations' },
];

/**
 * Build the panel chrome once and wire it once.
 *
 * Pre:  `_modal` exists and is empty.
 * Post: header, stats bar, toolbar and an empty list container are in place,
 *       with every listener attached to an element that now outlives every
 *       render.
 * Inv:  nothing in here is rebuilt by _render. That is the whole point — the
 *       search box used to be destroyed and recreated on every keystroke and
 *       every 3s poll, which stole focus and the caret with it.
 */
function _buildChrome() {
  _modal.innerHTML = `
    <div class="act-header" id="act-header-drag">
      <div class="act-title">
        <span style="color:var(--red,#e06c75);display:inline-flex;">${ICONS.bolt}</span>
        System Activity &amp; Query Audit Log
      </div>
      <div class="act-controls">
        <button class="act-btn" id="act-refresh-btn" title="Refresh logs">
          ${ICONS.refresh}
          Refresh
        </button>
        <button class="act-btn danger" id="act-clear-btn" title="Clear logs older than 7 days">
          ${ICONS.trash}
          Prune
        </button>
        <button class="act-btn" id="act-close-btn" title="Close" style="padding:4px 8px;">${ICONS.close}</button>
      </div>
    </div>

    <div class="act-stats-bar">
      <div class="act-stat-item">Total Queries: <span class="act-stat-val" data-stat="total">0</span></div>
      <div class="act-stat-item">Running: <span class="act-stat-val" data-stat="running" style="color:var(--status-busy,#61afef);">0</span></div>
      <div class="act-stat-item">Errors: <span class="act-stat-val" data-stat="errors" style="color:var(--status-error,#e06c75);">0</span></div>
      <div class="act-stat-item" title="Runs that produced output but degraded to a fallback">Degraded: <span class="act-stat-val" data-stat="degraded" style="color:var(--status-warn,#d19a66);">0</span></div>
      <div style="flex:1;"></div>
      <div style="font-size:11px;opacity:0.6;">Auto-refreshes every 3s</div>
    </div>

    <div class="act-toolbar">
      <div class="act-filter-chips">
        ${MODULE_CHIPS.map(m => `
          <button class="act-chip ${(_currentModuleFilter === m.key) ? 'active' : ''}" data-module="${_esc(m.key)}">
            ${_esc(m.label)} <span class="act-chip-count" data-chip-count="${_esc(m.key)}">0</span>
          </button>
        `).join('')}
      </div>

      <div class="act-search-row">
        <input type="text" id="act-search-input" class="act-search-input" placeholder="Search queries by action, target, model, or payload…" value="${_esc(_searchQuery)}" />
        <select id="act-status-select" class="act-btn" style="font-size:12px;">
          <option value="all">All Statuses</option>
          <option value="completed">Completed</option>
          <option value="running">Running</option>
          <option value="error">Errors</option>
          <option value="fallback">Fallbacks</option>
          <option value="halted">Halted</option>
        </select>
      </div>
    </div>

    <div class="act-list-container" id="act-list"></div>
  `;

  const content = _modal;
  const header = _modal.querySelector('#act-header-drag');
  // The call was makeWindowDraggable(_modal, dragHandle) — a bare element
  // where an options object belongs, so `content` and `header` were both
  // undefined and the helper returned immediately. The header has advertised
  // `cursor: move` the whole time. This panel is its own content: it has no
  // .modal-content wrapper. Docking stays off because the dock rules are
  // written `.modal.modal-right-docked ...` and this panel is not a `.modal`.
  makeWindowDraggable(_modal, { content, header, enableDock: false });

  _modal.querySelector('#act-close-btn').addEventListener('click', close);
  _modal.querySelector('#act-refresh-btn').addEventListener('click', _fetchLogs);

  _modal.querySelector('#act-clear-btn').addEventListener('click', async () => {
    if (confirm('Prune system query logs older than 7 days?')) {
      await fetch('/api/system/activity-logs/clear?older_than_days=7', { method: 'DELETE' });
      _fetchLogs();
    }
  });

  _modal.querySelectorAll('.act-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      _currentModuleFilter = chip.getAttribute('data-module');
      _modal.querySelectorAll('.act-chip').forEach(c => {
        c.classList.toggle('active', c === chip);
      });
      _fetchLogs();
    });
  });

  const statusSel = _modal.querySelector('#act-status-select');
  statusSel.value = _currentStatusFilter;
  statusSel.addEventListener('change', (e) => {
    _currentStatusFilter = e.target.value;
    _fetchLogs();
  });

  _modal.querySelector('#act-search-input').addEventListener('input', (e) => {
    _searchQuery = e.target.value;
    _fetchLogs();
  });

  // One delegated listener on the container, so re-rendering the rows does
  // not orphan per-row listeners or need them re-attached.
  _modal.querySelector('#act-list').addEventListener('click', (e) => {
    const row = e.target.closest('.act-row');
    if (!row) return;
    const id = row.getAttribute('data-id');
    if (_expandedLogIds.has(id)) _expandedLogIds.delete(id);
    else _expandedLogIds.add(id);
    _render();
  });
}

/**
 * Refresh the volatile parts: the four counters, the chip counts, the rows.
 *
 * Pre:  _buildChrome has run.
 * Post: the panel shows current data.
 * Inv:  no focused element is replaced. A caret in the search box survives
 *       both a keystroke-triggered refresh and the 3s poll.
 */
function _render() {
  if (!_modal) return;
  const list = _modal.querySelector('#act-list');
  if (!list) return;

  const total = _stats?.total_queries || 0;
  const modCounts = _stats?.counts_by_module || {};
  const counts = {
    total,
    running: _stats?.running_count || 0,
    errors: _stats?.error_count || 0,
    // Reported beside errors rather than folded into them: a degraded run still
    // produced output, and summing the two would hide which happened.
    degraded: _stats?.fallback_count || 0,
  };
  for (const [key, value] of Object.entries(counts)) {
    const el = _modal.querySelector(`[data-stat="${key}"]`);
    if (el) el.textContent = value;
  }
  for (const chip of MODULE_CHIPS) {
    const el = _modal.querySelector(`[data-chip-count="${chip.key}"]`);
    if (el) el.textContent = chip.key === 'all' ? total : (modCounts[chip.key] || 0);
  }

  let rowsHtml = '';
  if (_logs.length === 0) {
    rowsHtml = '<div style="text-align:center;padding:40px;opacity:0.5;font-size:12px;">No system queries match your filter.</div>';
  } else {
    rowsHtml = _logs.map(log => {
      const isExp = _expandedLogIds.has(log.id);
      const statusCls = `act-status-${log.status || 'completed'}`;
      const statusIcon = _statusIcon(log.status);

      let detailHtml = '';
      if (isExp) {
        detailHtml = `
          <div class="act-detail-drawer">
            ${log.prompt_preview ? `
              <div class="act-detail-section">
                <div class="act-detail-label">Input Prompt / Query Payload:</div>
                <div class="act-detail-box">${_esc(log.prompt_preview)}</div>
              </div>
            ` : ''}
            ${log.result_preview ? `
              <div class="act-detail-section">
                <div class="act-detail-label">Execution Result / Output:</div>
                <div class="act-detail-box">${_esc(log.result_preview)}</div>
              </div>
            ` : ''}
            ${log.error ? `
              <div class="act-detail-section">
                <div class="act-detail-label">Error Diagnostics:</div>
                <div class="act-detail-box" style="border-color:var(--status-error,#e06c75);color:var(--status-error,#e06c75);">${_esc(log.error)}</div>
              </div>
            ` : ''}
            <div class="act-detail-section">
              <div class="act-detail-label">Execution Metadata:</div>
              <div class="act-detail-box">Log ID: ${log.id}
Timestamp: ${log.timestamp}
Query Type: ${log.query_type}
Endpoint: ${log.endpoint_url || 'Default'}
Duration: ${_formatDuration(log.duration_ms)}
Tokens: ${log.tokens_used || '—'}
Repeat Count: ${log.repeat_count || 1}
Metadata: ${JSON.stringify(log.metadata || {}, null, 2)}</div>
            </div>
          </div>
        `;
      }

      return `
        <div class="act-row ${isExp ? 'expanded' : ''}" data-id="${_esc(log.id)}">
          <div class="act-row-header">
            <div class="act-row-left">
              <span class="act-status-badge ${statusCls}">${statusIcon}${_esc(log.status)}</span>
              <span class="act-module-tag">${_esc(log.module)}</span>
              <span class="act-target-title">${_esc(log.target_name || log.action)}</span>
              ${log.repeat_count > 1 ? `<span class="act-repeat-badge">x${log.repeat_count}</span>` : ''}
            </div>
            <div class="act-row-right">
              ${log.model ? `<span class="act-model-pill">${_esc(log.model)}</span>` : ''}
              ${log.duration_ms !== null ? `<span class="act-latency-badge">${_formatDuration(log.duration_ms)}</span>` : ''}
              <span>${_formatDate(log.timestamp)}</span>
            </div>
          </div>
          <div class="act-preview-text">
            ${_esc(log.result_preview || log.prompt_preview || log.action)}
          </div>
          ${detailHtml}
        </div>
      `;
    }).join('');
  }

  list.innerHTML = rowsHtml;
}

export function open() {
  _injectStyles();
  if (!_modal) {
    _modal = document.createElement('div');
    _modal.id = 'activity-log-modal';
    // Own root class. The id stays: app.js:1130 and modalManager.js:1427 both
    // address this panel by it. The `modal` class is what had to go — see the
    // .activity-log-panel rule for why.
    _modal.className = 'activity-log-panel hidden';
    document.body.appendChild(_modal);
    // Built once per panel, not per render. close() hides rather than
    // destroys, so reopening reuses this chrome and its listeners.
    _buildChrome();
  }

  _modal.classList.remove('hidden');
  _modal.style.display = 'flex';
  _open = true;
  document.getElementById('tool-activity-log-btn')?.classList.add('active');

  _fetchLogs();
  if (!_pollInterval) {
    _pollInterval = setInterval(_fetchLogs, 3000);
  }
}

export function close() {
  if (_modal) {
    _modal.classList.add('hidden');
    _modal.style.display = 'none';
  }
  _open = false;
  document.getElementById('tool-activity-log-btn')?.classList.remove('active');

  if (_pollInterval) {
    clearInterval(_pollInterval);
    _pollInterval = null;
  }
}

export function isOpen() {
  return _open;
}

// Background poller for sidebar running dot indicator even when closed
setInterval(async () => {
  if (_open) return;
  try {
    const res = await fetch('/api/system/activity-logs/stats');
    if (res.ok) {
      _stats = await res.json();
      _updateSidebarIndicator();
    }
  } catch {}
}, 10000);

export default { open, close, isOpen };
