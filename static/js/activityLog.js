// static/js/activityLog.js
/**
 * Activity Log Module — Unified Observability & Audit Hub for Odysseus.
 * Displays all non-chat system queries, background jobs, tool executions, and model latencies.
 */

import { makeWindowDraggable } from './windowDrag.js';
import uiModule from './ui.js';
import markdownModule from './markdown.js';

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
    #activity-log-modal {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: min(920px, 94vw);
      height: min(720px, 86vh);
      background: var(--bg, #1e1e24);
      color: var(--fg, #e0e0e0);
      border: 1px solid var(--border, #333);
      border-radius: 12px;
      box-shadow: 0 16px 48px rgba(0,0,0,0.65);
      z-index: 100060;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      font-family: inherit;
    }
    #activity-log-modal.hidden { display: none !important; }

    .act-header {
      padding: 14px 18px;
      background: var(--bg-elev, #25252d);
      border-bottom: 1px solid var(--border, #333);
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
      background: var(--bg, #222);
      color: var(--fg, #ddd);
      border: 1px solid var(--border, #444);
      border-radius: 6px;
      padding: 5px 10px;
      font-size: 12px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: all 0.15s;
    }
    .act-btn:hover {
      background: var(--border, #3a3a3a);
      border-color: var(--accent, #e8a33d);
    }
    .act-btn.danger:hover {
      background: #7f1d1d;
      border-color: #ef4444;
      color: #fff;
    }

    .act-stats-bar {
      padding: 8px 18px;
      background: rgba(0,0,0,0.2);
      border-bottom: 1px solid var(--border, #2a2a30);
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
      color: var(--accent, #e8a33d);
    }

    .act-toolbar {
      padding: 10px 18px;
      border-bottom: 1px solid var(--border, #2a2a30);
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
      background: var(--bg-elev, #25252d);
      color: var(--fg-muted, #999);
      border: 1px solid var(--border, #3a3a44);
      border-radius: 20px;
      padding: 3px 10px;
      font-size: 11.5px;
      cursor: pointer;
      transition: all 0.15s;
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }
    .act-chip:hover {
      color: var(--fg, #fff);
      border-color: #555;
    }
    .act-chip.active {
      background: var(--accent, #e8a33d);
      color: #111;
      border-color: var(--accent, #e8a33d);
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
      background: var(--bg-elev, #18181f);
      border: 1px solid var(--border, #3a3a44);
      border-radius: 6px;
      padding: 6px 12px;
      font-size: 12.5px;
      color: var(--fg, #eee);
    }
    .act-search-input:focus {
      outline: none;
      border-color: var(--accent, #e8a33d);
    }

    .act-list-container {
      flex: 1;
      overflow-y: auto;
      padding: 12px 18px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .act-row {
      background: var(--bg-elev, #25252d);
      border: 1px solid var(--border, #333);
      border-radius: 8px;
      padding: 10px 14px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      transition: border-color 0.15s;
      cursor: pointer;
    }
    .act-row:hover {
      border-color: #555;
    }
    .act-row.expanded {
      border-color: var(--accent, #e8a33d);
      background: var(--bg-elev, #282832);
    }

    .act-row-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .act-row-left {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    .act-status-badge {
      font-size: 10px;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .act-status-completed { background: rgba(34, 197, 94, 0.18); color: #22c55e; border: 1px solid rgba(34, 197, 94, 0.4); }
    .act-status-running   { background: rgba(234, 179, 8, 0.18); color: #eab308; border: 1px solid rgba(234, 179, 8, 0.4); }
    .act-status-error     { background: rgba(239, 68, 68, 0.18); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4); }
    .act-status-fallback  { background: rgba(249, 115, 22, 0.18); color: #f97316; border: 1px solid rgba(249, 115, 22, 0.4); }
    .act-status-halted    { background: rgba(168, 85, 247, 0.18); color: #a855f7; border: 1px solid rgba(168, 85, 247, 0.4); }

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
      background: #3b82f6;
      color: #fff;
      padding: 1px 5px;
      border-radius: 8px;
    }

    .act-row-right {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 11px;
      color: var(--fg-muted, #888);
      flex-shrink: 0;
    }
    .act-model-pill {
      font-family: monospace;
      font-size: 10.5px;
      background: rgba(0,0,0,0.3);
      padding: 2px 6px;
      border-radius: 4px;
      color: #93c5fd;
      border: 1px solid rgba(147, 197, 253, 0.2);
    }
    .act-latency-badge {
      font-family: monospace;
      font-size: 10.5px;
      color: #a3e635;
    }

    .act-preview-text {
      font-size: 12px;
      line-height: 1.4;
      color: var(--fg, #ccc);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .act-detail-drawer {
      margin-top: 8px;
      padding-top: 10px;
      border-top: 1px solid var(--border, #3a3a44);
      display: flex;
      flex-direction: column;
      gap: 10px;
      font-size: 12px;
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
      color: var(--accent, #e8a33d);
    }
    .act-detail-box {
      background: rgba(0,0,0,0.35);
      border: 1px solid var(--border, #333);
      border-radius: 6px;
      padding: 8px 12px;
      font-family: monospace;
      font-size: 11.5px;
      white-space: pre-wrap;
      max-height: 240px;
      overflow-y: auto;
      color: #eee;
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

function _render() {
  if (!_modal) return;

  const total = _stats?.total_queries || 0;
  const running = _stats?.running_count || 0;
  const errors = _stats?.error_count || 0;
  const modCounts = _stats?.counts_by_module || {};

  const modules = [
    { key: 'all', label: 'All', count: total },
    { key: 'projects', label: 'Projects', count: modCounts.projects || 0 },
    { key: 'tasks', label: 'Tasks', count: modCounts.tasks || 0 },
    { key: 'email', label: 'Email', count: modCounts.email || 0 },
    { key: 'operations', label: 'Operations', count: modCounts.operations || 0 },
  ];

  let rowsHtml = '';
  if (_logs.length === 0) {
    rowsHtml = '<div style="text-align:center;padding:40px;color:var(--fg-muted,#777);">No system queries match your filter.</div>';
  } else {
    rowsHtml = _logs.map(log => {
      const isExp = _expandedLogIds.has(log.id);
      const statusCls = `act-status-${log.status || 'completed'}`;
      const statusIcon = log.status === 'running' ? '⏳' : (log.status === 'error' ? '🔴' : (log.status === 'fallback' ? '🟡' : (log.status === 'halted' ? '⏹️' : '🟢')));

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
                <div class="act-detail-label" style="color:#ef4444;">Error Diagnostics:</div>
                <div class="act-detail-box" style="border-color:#ef4444;color:#fca5a5;">${_esc(log.error)}</div>
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
              <span class="act-status-badge ${statusCls}">${statusIcon} ${log.status}</span>
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

  _modal.innerHTML = `
    <div class="act-header" id="act-header-drag">
      <div class="act-title">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--accent,#e8a33d);">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
        </svg>
        System Activity & Query Audit Log
      </div>
      <div class="act-controls">
        <button class="act-btn" id="act-refresh-btn" title="Refresh logs">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          Refresh
        </button>
        <button class="act-btn danger" id="act-clear-btn" title="Clear logs older than 7 days">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
          Prune
        </button>
        <button class="act-btn" id="act-close-btn" style="padding:4px 8px;">✕</button>
      </div>
    </div>

    <div class="act-stats-bar">
      <div class="act-stat-item">Total Queries: <span class="act-stat-val">${total}</span></div>
      <div class="act-stat-item">Running: <span class="act-stat-val" style="color:#eab308;">${running}</span></div>
      <div class="act-stat-item">Errors: <span class="act-stat-val" style="color:#ef4444;">${errors}</span></div>
      <div style="flex:1;"></div>
      <div style="font-size:11px;opacity:0.6;">Auto-refreshes every 3s</div>
    </div>

    <div class="act-toolbar">
      <div class="act-filter-chips">
        ${modules.map(m => `
          <button class="act-chip ${(_currentModuleFilter === m.key) ? 'active' : ''}" data-module="${_esc(m.key)}">
            ${_esc(m.label)} <span class="act-chip-count">${m.count}</span>
          </button>
        `).join('')}
      </div>

      <div class="act-search-row">
        <input type="text" id="act-search-input" class="act-search-input" placeholder="🔍 Search queries by action, target, model, or payload..." value="${_esc(_searchQuery)}" />
        <select id="act-status-select" class="act-btn" style="font-size:12px;">
          <option value="all" ${_currentStatusFilter === 'all' ? 'selected' : ''}>All Statuses</option>
          <option value="completed" ${_currentStatusFilter === 'completed' ? 'selected' : ''}>Completed</option>
          <option value="running" ${_currentStatusFilter === 'running' ? 'selected' : ''}>Running</option>
          <option value="error" ${_currentStatusFilter === 'error' ? 'selected' : ''}>Errors</option>
          <option value="fallback" ${_currentStatusFilter === 'fallback' ? 'selected' : ''}>Fallbacks</option>
          <option value="halted" ${_currentStatusFilter === 'halted' ? 'selected' : ''}>Halted</option>
        </select>
      </div>
    </div>

    <div class="act-list-container">
      ${rowsHtml}
    </div>
  `;

  // Wire events
  const dragHandle = _modal.querySelector('#act-header-drag');
  if (dragHandle) makeWindowDraggable(_modal, dragHandle);

  _modal.querySelector('#act-close-btn')?.addEventListener('click', close);
  _modal.querySelector('#act-refresh-btn')?.addEventListener('click', _fetchLogs);

  _modal.querySelector('#act-clear-btn')?.addEventListener('click', async () => {
    if (confirm('Prune system query logs older than 7 days?')) {
      await fetch('/api/system/activity-logs/clear?older_than_days=7', { method: 'DELETE' });
      _fetchLogs();
    }
  });

  _modal.querySelectorAll('.act-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      _currentModuleFilter = chip.getAttribute('data-module');
      _fetchLogs();
    });
  });

  const statusSel = _modal.querySelector('#act-status-select');
  if (statusSel) {
    statusSel.addEventListener('change', (e) => {
      _currentStatusFilter = e.target.value;
      _fetchLogs();
    });
  }

  const searchInp = _modal.querySelector('#act-search-input');
  if (searchInp) {
    searchInp.addEventListener('input', (e) => {
      _searchQuery = e.target.value;
      _fetchLogs();
    });
  }

  _modal.querySelectorAll('.act-row').forEach(row => {
    row.addEventListener('click', () => {
      const id = row.getAttribute('data-id');
      if (_expandedLogIds.has(id)) _expandedLogIds.delete(id);
      else _expandedLogIds.add(id);
      _render();
    });
  });
}

export function open() {
  _injectStyles();
  if (!_modal) {
    _modal = document.createElement('div');
    _modal.id = 'activity-log-modal';
    _modal.className = 'modal hidden';
    document.body.appendChild(_modal);
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
