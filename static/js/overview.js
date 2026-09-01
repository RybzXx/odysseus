// static/js/overview.js
/**
 * Executive Overview Hub — Morning Briefing & Cross-Module Operational Cockpit.
 *
 * Core Features:
 * - High-density Morning Briefing KPI banner.
 * - 7-Day Email Digest with multi-account filtering, date presets, and AI urgency badges.
 * - Responsive Active Projects Matrix: wide-screen multi-column checklists vs. compact accordions.
 * - Inbound Operations & Inquiries Radar across all 5 operational pipelines with Email Draft bridge.
 * - Multi-tier SWR (Stale-While-Revalidate) caching for instant sub-10ms loads.
 * - Strictly zero emojis; native Odysseus Feather/Lucide inline SVG iconography.
 * - Real-time cross-layer state synchronicity via DOM event bus.
 */

import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';

let _open = false;
let _modal = null;
let _overviewData = null;
let _loading = false;
let _stylesInjected = false;

// Filter states
let _emailAccountFilter = 'all';
let _emailDaysFilter = 7;
let _emailUnreadOnly = false;
let _expandedProjectIds = new Set();
let _opsFilterSource = 'all';

// Registered widget descriptors
const _widgets = [];

/**
 * Register a modular dashboard widget.
 */
export function registerWidget(descriptor) {
  if (!descriptor || !descriptor.id) return;
  const existingIdx = _widgets.findIndex(w => w.id === descriptor.id);
  if (existingIdx >= 0) {
    _widgets[existingIdx] = descriptor;
  } else {
    _widgets.push(descriptor);
  }
}

// Inline SVG Icon Helpers (Strictly No Emojis)
const ICONS = {
  dashboard: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></svg>`,
  mail: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>`,
  folder: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`,
  operations: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="5" height="16" rx="1"/><rect x="9.5" y="4" width="5" height="10" rx="1"/><rect x="16" y="4" width="5" height="13" rx="1"/></svg>`,
  checkCircle: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>`,
  alertCircle: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
  clock: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
  externalLink: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>`,
  refresh: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>`,
  close: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
  chevronDown: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>`,
  send: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>`,
  sparkle: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`,
};

function _injectStyles() {
  if (_stylesInjected) return;
  _stylesInjected = true;
  const style = document.createElement('style');
  style.id = 'odysseus-overview-styles';
  style.textContent = `
    .overview-modal {
      position: fixed;
      top: 36px;
      left: 50%;
      transform: translateX(-50%);
      width: min(1320px, calc(100vw - 32px));
      height: min(880px, calc(100vh - 64px));
      max-height: calc(100vh - 48px);
      background: var(--panel, #1e2227);
      border: 1px solid var(--border, rgba(255,255,255,0.12));
      border-radius: 10px;
      box-shadow: 0 16px 48px rgba(0,0,0,0.5);
      z-index: 310;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      font-family: var(--font-family, system-ui, sans-serif);
      color: var(--fg, #abb2bf);
    }
    .overview-header {
      padding: 10px 16px;
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
      display: flex;
      align-items: center;
      gap: 12px;
      background: var(--bg, #282c34);
      user-select: none;
      flex-shrink: 0;
    }
    .overview-title-group {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 600;
      font-size: 14px;
      color: var(--fg, #fff);
    }
    .overview-header-actions {
      margin-left: auto;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .overview-btn {
      background: rgba(255,255,255,0.06);
      border: 1px solid var(--border, rgba(255,255,255,0.1));
      color: var(--fg, #abb2bf);
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 12px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: background 0.15s ease, border-color 0.15s ease;
    }
    .overview-btn:hover {
      background: rgba(255,255,255,0.12);
      border-color: rgba(255,255,255,0.2);
      color: #fff;
    }
    .overview-btn.active {
      background: var(--brand-color, #e06c75);
      border-color: var(--brand-color, #e06c75);
      color: #fff;
    }
    .overview-body {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      background: var(--bg, #181a1f);
    }
    .overview-kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 12px;
      flex-shrink: 0;
    }
    .overview-kpi-card {
      background: var(--panel, #21252b);
      border: 1px solid var(--border, rgba(255,255,255,0.08));
      border-radius: 8px;
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      position: relative;
      overflow: hidden;
    }
    .overview-kpi-card.urgent {
      border-color: rgba(224, 108, 117, 0.4);
      background: rgba(224, 108, 117, 0.04);
    }
    .overview-kpi-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      opacity: 0.7;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .overview-kpi-value {
      font-size: 22px;
      font-weight: 700;
      font-family: 'Fira Code', monospace;
      color: var(--fg, #fff);
    }
    .overview-kpi-sub {
      font-size: 11px;
      opacity: 0.6;
    }
    .overview-main-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      flex: 1;
    }
    @media (max-width: 980px) {
      .overview-main-grid {
        grid-template-columns: 1fr;
      }
    }
    .overview-panel {
      background: var(--panel, #21252b);
      border: 1px solid var(--border, rgba(255,255,255,0.08));
      border-radius: 8px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .overview-panel-header {
      padding: 10px 14px;
      background: rgba(0,0,0,0.15);
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.06));
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      font-weight: 600;
    }
    .overview-panel-body {
      padding: 12px;
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .overview-controls-row {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 4px;
    }
    .overview-select {
      background: rgba(0,0,0,0.25);
      border: 1px solid var(--border, rgba(255,255,255,0.12));
      color: var(--fg, #abb2bf);
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 12px;
    }
    /* Email items */
    .overview-email-item {
      background: rgba(0,0,0,0.18);
      border: 1px solid var(--border, rgba(255,255,255,0.06));
      border-radius: 6px;
      padding: 9px 12px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      cursor: pointer;
      transition: background 0.15s ease, border-color 0.15s ease;
    }
    .overview-email-item:hover {
      background: rgba(255,255,255,0.04);
      border-color: rgba(255,255,255,0.15);
    }
    .overview-email-item.unread {
      border-left: 3px solid var(--brand-color, #e06c75);
    }
    .overview-email-top {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
    }
    .overview-email-sender {
      font-weight: 600;
      color: var(--fg, #fff);
    }
    .overview-email-date {
      margin-left: auto;
      font-size: 11px;
      opacity: 0.5;
    }
    .overview-email-subject {
      font-size: 13px;
      color: var(--fg, #dcdfe4);
      font-weight: 500;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .overview-email-snippet {
      font-size: 11px;
      opacity: 0.65;
      line-height: 1.4;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .overview-ai-pill {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      background: rgba(97, 175, 239, 0.12);
      border: 1px solid rgba(97, 175, 239, 0.3);
      color: #61afef;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 11px;
      margin-top: 2px;
      width: fit-content;
    }
    .overview-urgency-badge {
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 2px 5px;
      border-radius: 3px;
      letter-spacing: 0.4px;
    }
    .overview-urgency-badge.critical {
      background: rgba(224, 108, 117, 0.2);
      color: #e06c75;
      border: 1px solid #e06c75;
    }
    .overview-urgency-badge.urgent {
      background: rgba(229, 192, 123, 0.2);
      color: #e5c07b;
      border: 1px solid #e5c07b;
    }
    /* Projects responsive container */
    .overview-projects-container {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .overview-project-card {
      background: rgba(0,0,0,0.18);
      border: 1px solid var(--border, rgba(255,255,255,0.06));
      border-radius: 6px;
      padding: 10px 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .overview-project-header-row {
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
    }
    .overview-project-name {
      font-size: 13px;
      font-weight: 600;
      color: var(--fg, #fff);
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .overview-project-name:hover {
      color: var(--brand-color, #e06c75);
    }
    .overview-project-tasks-meter {
      margin-left: auto;
      font-size: 11px;
      font-family: 'Fira Code', monospace;
      opacity: 0.7;
    }
    .overview-progress-bar {
      height: 4px;
      background: rgba(255,255,255,0.08);
      border-radius: 2px;
      overflow: hidden;
    }
    .overview-progress-fill {
      height: 100%;
      background: var(--brand-color, #e06c75);
      border-radius: 2px;
      transition: width 0.2s ease;
    }
    .overview-task-list {
      display: flex;
      flex-direction: column;
      gap: 5px;
      margin-top: 4px;
      padding-left: 4px;
    }
    .overview-task-row {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
    }
    .overview-check-dot {
      width: 14px;
      height: 14px;
      border-radius: 50%;
      border: 1.5px solid var(--border, rgba(255,255,255,0.3));
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      transition: all 0.15s ease;
    }
    .overview-check-dot:hover {
      border-color: var(--brand-color, #e06c75);
    }
    .overview-check-dot.checked {
      background: var(--brand-color, #e06c75);
      border-color: var(--brand-color, #e06c75);
      color: #fff;
    }
    .overview-task-title {
      color: var(--fg, #abb2bf);
      flex: 1;
    }
    .overview-task-title.completed {
      text-decoration: line-through;
      opacity: 0.5;
    }
    /* Operations items */
    .overview-inquiry-item {
      background: rgba(0,0,0,0.18);
      border: 1px solid var(--border, rgba(255,255,255,0.06));
      border-radius: 6px;
      padding: 9px 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .overview-inquiry-item.overdue {
      border-color: rgba(224, 108, 117, 0.4);
      background: rgba(224, 108, 117, 0.03);
    }
    .overview-inquiry-header {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
    }
    .overview-source-badge {
      font-size: 10px;
      font-weight: 600;
      padding: 2px 6px;
      border-radius: 3px;
      background: rgba(255,255,255,0.08);
      text-transform: capitalize;
    }
    .overview-inquiry-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 4px;
    }
    .overview-empty {
      padding: 24px;
      text-align: center;
      opacity: 0.5;
      font-size: 12px;
    }
  `;
  document.head.appendChild(style);
}

function _getModal() {
  if (_modal && document.body.contains(_modal)) return _modal;
  _injectStyles();

  _modal = document.createElement('div');
  _modal.id = 'overview-modal';
  _modal.className = 'overview-modal hidden';
  _modal.setAttribute('role', 'dialog');
  _modal.setAttribute('aria-label', 'Executive Overview Hub');

  _modal.innerHTML = `
    <div class="overview-header" id="overview-drag-header">
      <div class="overview-title-group">
        ${ICONS.dashboard}
        <span>Executive Overview Hub</span>
      </div>
      <div class="overview-header-actions">
        <span id="overview-cache-status" style="font-size:11px;opacity:0.6;font-family:'Fira Code',monospace;"></span>
        <button class="overview-btn" id="overview-open-organisers-btn" title="Open AI Work Organisers">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
          <span>AI Organisers</span>
        </button>
        <button class="overview-btn" id="overview-refresh-btn" title="Refresh Dashboard">
          ${ICONS.refresh}
          <span>Refresh</span>
        </button>
        <button class="overview-btn" id="overview-minimize-btn" title="Minimize">_</button>
        <button class="overview-btn" id="overview-close-btn" title="Close (Esc)">${ICONS.close}</button>
      </div>
    </div>
    <div class="overview-body" id="overview-body-container">
      <div class="overview-empty">Loading executive briefing...</div>
    </div>
  `;

  document.body.appendChild(_modal);

  const header = _modal.querySelector('#overview-drag-header');
  makeWindowDraggable(_modal, { header });

  _modal.querySelector('#overview-close-btn').addEventListener('click', closeOverview);
  _modal.querySelector('#overview-open-organisers-btn').addEventListener('click', () => {
    if (window.openOrganisers) {
      window.openOrganisers();
    }
  });
  _modal.querySelector('#overview-minimize-btn').addEventListener('click', () => {
    Modals.minimize('overview-modal');
  });
  _modal.querySelector('#overview-refresh-btn').addEventListener('click', () => {
    refreshOverview(true);
  });

  return _modal;
}

/**
 * Fetch overview briefing data from the backend.
 */
async function _fetchOverviewData(forceRefresh = false) {
  _loading = true;
  _updateCacheStatusBanner();
  try {
    const res = await fetch(`/api/overview?email_days=${_emailDaysFilter}&force_refresh=${forceRefresh}&_=${Date.now()}`, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _overviewData = await res.json();
    _render();
  } catch (err) {
    console.error('Failed to load overview data:', err);
    const body = _modal ? _modal.querySelector('#overview-body-container') : null;
    if (body && !_overviewData) {
      body.innerHTML = `<div class="overview-empty" style="color:var(--red,#e06c75)">Failed to load briefing: ${err.message}</div>`;
    }
  } finally {
    _loading = false;
    _updateCacheStatusBanner();
  }
}

function _updateCacheStatusBanner() {
  if (!_modal) return;
  const banner = _modal.querySelector('#overview-cache-status');
  if (!banner) return;

  if (_loading) {
    banner.textContent = 'Updating...';
    return;
  }
  if (_overviewData && _overviewData.cached_at) {
    const timeStr = _overviewData.cached_at.substring(11, 16);
    banner.textContent = `Synced ${timeStr} UTC ${_overviewData.is_stale ? '(Revalidating)' : ''}`;
  }
}

/**
 * Main render function.
 */
function _render() {
  if (!_modal || !_overviewData) return;
  const container = _modal.querySelector('#overview-body-container');
  if (!container) return;

  const kpis = _overviewData.kpis || {};
  const emailsData = _overviewData.email_digest || { accounts: [], emails: [] };
  const projectsData = _overviewData.projects_matrix || [];
  const opsData = _overviewData.operations_radar || { inquiries: [] };

  // Filter emails
  let filteredEmails = emailsData.emails || [];
  if (_emailAccountFilter !== 'all') {
    filteredEmails = filteredEmails.filter(e => e.account_id === _emailAccountFilter);
  }
  if (_emailUnreadOnly) {
    filteredEmails = filteredEmails.filter(e => !e.read);
  }

  // Filter operations
  let filteredOps = opsData.inquiries || [];
  if (_opsFilterSource !== 'all') {
    filteredOps = filteredOps.filter(i => i.source === _opsFilterSource);
  }

  const daysLabel = _emailDaysFilter === 1 ? 'Today' : `${_emailDaysFilter}d`;

  container.innerHTML = `
    <!-- Top KPI Briefing Banner -->
    <div class="overview-kpi-grid">
      <div class="overview-kpi-card ${kpis.urgent_emails > 0 ? 'urgent' : ''}">
        <div class="overview-kpi-label">${ICONS.mail} Urgent Emails (${daysLabel})</div>
        <div class="overview-kpi-value">${kpis.urgent_emails || 0}</div>
        <div class="overview-kpi-sub">${kpis.unread_emails || 0} unread across ${emailsData.accounts.length || 1} accounts</div>
      </div>
      <div class="overview-kpi-card">
        <div class="overview-kpi-label">${ICONS.folder} Open Tasks</div>
        <div class="overview-kpi-value">${kpis.open_tasks || 0}</div>
        <div class="overview-kpi-sub">Across ${kpis.active_projects || 0} active workspaces</div>
      </div>
      <div class="overview-kpi-card ${kpis.overdue_inquiries > 0 ? 'urgent' : ''}">
        <div class="overview-kpi-label">${ICONS.operations} Inbound Inquiries</div>
        <div class="overview-kpi-value">${kpis.pending_inquiries || 0}</div>
        <div class="overview-kpi-sub">${kpis.overdue_inquiries || 0} overdue follow-up(s)</div>
      </div>
    </div>

    <!-- Main Dual Grid Layout -->
    <div class="overview-main-grid">
      <!-- LEFT COLUMN: Email Digest & Operations Radar -->
      <div style="display:flex;flex-direction:column;gap:16px;">
        <!-- Email Digest Panel -->
        <div class="overview-panel">
          <div class="overview-panel-header">
            ${ICONS.mail}
            <span>Email Stream (${daysLabel})</span>
          </div>
          <div class="overview-panel-body">
            <div class="overview-controls-row">
              <select class="overview-select" id="overview-email-acc-select">
                <option value="all">All Accounts (${emailsData.accounts.length})</option>
                ${emailsData.accounts.map(a => `<option value="${a.id}" ${_emailAccountFilter === a.id ? 'selected' : ''}>${a.name}</option>`).join('')}
              </select>
              <button class="overview-btn ${_emailDaysFilter === 1 ? 'active' : ''}" data-days="1">Today</button>
              <button class="overview-btn ${_emailDaysFilter === 3 ? 'active' : ''}" data-days="3">3d</button>
              <button class="overview-btn ${_emailDaysFilter === 7 ? 'active' : ''}" data-days="7">7d</button>
              <label style="margin-left:auto;font-size:11px;display:flex;align-items:center;gap:4px;cursor:pointer;">
                <input type="checkbox" id="overview-unread-toggle" ${_emailUnreadOnly ? 'checked' : ''}>
                Unread only
              </label>
            </div>

            <div style="display:flex;flex-direction:column;gap:8px;max-height:360px;overflow-y:auto;">
              ${filteredEmails.length === 0 ? '<div class="overview-empty">No emails in this duration.</div>' : ''}
              ${filteredEmails.map(em => `
                <div class="overview-email-item ${!em.read ? 'unread' : ''}" data-email-id="${em.id}" data-email-uid="${em.uid || ''}" data-email-account-id="${em.account_id || ''}" data-email-folder="${em.folder || 'INBOX'}">
                  <div class="overview-email-top">
                    <span class="overview-email-sender">${_escape(em.sender_name)}</span>
                    ${em.urgency === 'critical' ? `<span class="overview-urgency-badge critical">Critical</span>` : ''}
                    ${em.urgency === 'urgent' ? `<span class="overview-urgency-badge urgent">Urgent</span>` : ''}
                    <span class="overview-email-date">${_formatDate(em.timestamp)}</span>
                  </div>
                  <div class="overview-email-subject">${_escape(em.subject)}</div>
                  ${em.snippet ? `<div class="overview-email-snippet">${_escape(em.snippet)}</div>` : ''}
                  ${em.ai_comment ? `<div class="overview-ai-pill">${ICONS.sparkle} <span>${_escape(em.ai_comment)}</span></div>` : ''}
                </div>
              `).join('')}
            </div>
          </div>
        </div>

        <!-- Operations Radar Panel -->
        <div class="overview-panel">
          <div class="overview-panel-header">
            ${ICONS.operations}
            <span>Operations & Inquiries Radar</span>
          </div>
          <div class="overview-panel-body">
            <div class="overview-controls-row">
              <select class="overview-select" id="overview-ops-source-select">
                <option value="all">All Channels</option>
                <option value="booking" ${_opsFilterSource === 'booking' ? 'selected' : ''}>Registration</option>
                <option value="contact" ${_opsFilterSource === 'contact' ? 'selected' : ''}>Contact</option>
                <option value="curated" ${_opsFilterSource === 'curated' ? 'selected' : ''}>Curated</option>
                <option value="queue" ${_opsFilterSource === 'queue' ? 'selected' : ''}>WhatsApp Queue</option>
              </select>
            </div>

            <div style="display:flex;flex-direction:column;gap:8px;max-height:300px;overflow-y:auto;">
              ${filteredOps.length === 0 ? '<div class="overview-empty">No recent operations inquiries.</div>' : ''}
              ${filteredOps.map(op => `
                <div class="overview-inquiry-item ${op.is_overdue ? 'overdue' : ''}">
                  <div class="overview-inquiry-header">
                    <span class="overview-source-badge">${op.source}</span>
                    <strong style="color:#fff;">${_escape(op.name)}</strong>
                    <span style="font-size:11px;opacity:0.6;margin-left:auto;">${op.status}</span>
                  </div>
                  <div style="font-size:12px;opacity:0.85;">${_escape(op.summary || 'Enquiry record')}</div>
                  ${op.is_overdue ? `<div style="color:#e06c75;font-size:11px;display:flex;align-items:center;gap:4px;">${ICONS.alertCircle} Overdue action (${op.next_action_date})</div>` : ''}
                  <div class="overview-inquiry-actions">
                    ${op.email ? `
                      <button class="overview-btn" data-draft-email="${_escape(op.email)}" data-draft-name="${_escape(op.name)}" data-draft-summary="${_escape(op.summary)}">
                        ${ICONS.send}
                        <span>Draft Reply</span>
                      </button>
                    ` : ''}
                    <button class="overview-btn" data-open-ops="${_escape(op.key)}" style="margin-left:auto;">
                      ${ICONS.externalLink}
                      <span>View in Operations</span>
                    </button>
                  </div>
                </div>
              `).join('')}
            </div>
          </div>
        </div>
      </div>

      <!-- RIGHT COLUMN: Responsive Active Projects Matrix -->
      <div class="overview-panel" style="flex:1;">
        <div class="overview-panel-header">
          ${ICONS.folder}
          <span>Active Projects & Tasks Matrix</span>
        </div>
        <div class="overview-panel-body">
          <div class="overview-projects-container">
            ${projectsData.length === 0 ? '<div class="overview-empty">No active projects configured.</div>' : ''}
            ${projectsData.map(proj => {
              const completedCount = proj.tasks.filter(t => t.completed).length;
              const totalCount = proj.tasks.length;
              const percent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;
              const isExpanded = _expandedProjectIds.has(proj.id);

              return `
                <div class="overview-project-card" data-project-id="${proj.id}">
                  <div class="overview-project-header-row" data-toggle-proj="${proj.id}">
                    <span class="overview-project-name" data-drill-proj="${proj.id}">
                      ${_escape(proj.name)}
                      ${ICONS.externalLink}
                    </span>
                    <span class="overview-project-tasks-meter">${completedCount}/${totalCount} tasks (${percent}%)</span>
                    <span style="opacity:0.5;transform:${isExpanded ? 'rotate(180deg)' : 'rotate(0)'};transition:transform .15s ease;">${ICONS.chevronDown}</span>
                  </div>
                  <div class="overview-progress-bar">
                    <div class="overview-progress-fill" style="width:${percent}%"></div>
                  </div>
                  ${proj.agent_summary ? `<div style="font-size:11px;opacity:0.75;line-height:1.4;">${_escape(proj.agent_summary)}</div>` : ''}

                  <!-- Tasks checklist -->
                  <div class="overview-task-list">
                    ${proj.tasks.slice(0, isExpanded ? 50 : 4).map(task => `
                      <div class="overview-task-row">
                        <div class="overview-check-dot ${task.completed ? 'checked' : ''}" data-task-id="${task.id}" data-task-proj="${proj.id}">
                          ${task.completed ? ICONS.checkCircle : ''}
                        </div>
                        <span class="overview-task-title ${task.completed ? 'completed' : ''}">${_escape(task.title)}</span>
                      </div>
                    `).join('')}
                    ${!isExpanded && proj.tasks.length > 4 ? `
                      <button class="overview-btn" data-expand-proj="${proj.id}" style="align-self:flex-start;margin-top:2px;font-size:11px;">
                        + ${proj.tasks.length - 4} more tasks...
                      </button>
                    ` : ''}
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      </div>
    </div>
  `;

  _bindEventListeners(container);
}

function _bindEventListeners(container) {
  // Email account selector
  const accSel = container.querySelector('#overview-email-acc-select');
  if (accSel) {
    accSel.addEventListener('change', (e) => {
      _emailAccountFilter = e.target.value;
      _render();
    });
  }

  // Email days preset buttons
  container.querySelectorAll('[data-days]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const days = parseInt(btn.dataset.days, 10) || 7;
      if (_emailDaysFilter === days) return;
      _emailDaysFilter = days;
      _fetchOverviewData(false);
    });
  });

  // Email item click to open in Email reader
  container.querySelectorAll('.overview-email-item').forEach(card => {
    card.addEventListener('click', async (e) => {
      e.stopPropagation();
      const uid = card.dataset.emailUid;
      const accountId = card.dataset.emailAccountId;
      const folder = card.dataset.emailFolder || 'INBOX';

      card.classList.remove('unread');

      try {
        if (window.openEmailLibrary) {
          window.openEmailLibrary({ folder, uid, accountId });
        } else {
          const mod = await import('./emailLibrary.js?v=20260815approvalsave1');
          if (mod && mod.openEmailLibrary) {
            mod.openEmailLibrary({ folder, uid, accountId });
          }
        }
      } catch (err) {
        console.error('Failed to open email:', err);
      }
    });
  });

  // Email unread toggle
  const unreadToggle = container.querySelector('#overview-unread-toggle');
  if (unreadToggle) {
    unreadToggle.addEventListener('change', (e) => {
      _emailUnreadOnly = e.target.checked;
      _render();
    });
  }

  // Operations source selector
  const opsSel = container.querySelector('#overview-ops-source-select');
  if (opsSel) {
    opsSel.addEventListener('change', (e) => {
      _opsFilterSource = e.target.value;
      _render();
    });
  }

  // Project drilldown button
  container.querySelectorAll('[data-drill-proj]').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      const projId = el.dataset.drillProj;
      if (window.projectsModule && window.projectsModule.openProjects) {
        closeOverview();
        window.projectsModule.openProjects(projId);
      }
    });
  });

  // Project accordion toggle
  container.querySelectorAll('[data-toggle-proj]').forEach(el => {
    el.addEventListener('click', () => {
      const projId = el.dataset.toggleProj;
      if (_expandedProjectIds.has(projId)) {
        _expandedProjectIds.delete(projId);
      } else {
        _expandedProjectIds.add(projId);
      }
      _render();
    });
  });

  container.querySelectorAll('[data-expand-proj]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      _expandedProjectIds.add(btn.dataset.expandProj);
      _render();
    });
  });

  // Task check-dot toggle
  container.querySelectorAll('.overview-check-dot').forEach(dot => {
    dot.addEventListener('click', async (e) => {
      e.stopPropagation();
      const taskId = dot.dataset.taskId;
      const projId = dot.dataset.taskProj;
      const willBeCompleted = !dot.classList.contains('checked');

      // Optimistic update
      dot.classList.toggle('checked', willBeCompleted);
      const titleEl = dot.nextElementSibling;
      if (titleEl) titleEl.classList.toggle('completed', willBeCompleted);

      try {
        const res = await fetch(`/api/projects/tasks/${taskId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ completed: willBeCompleted }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        // Broadcast cross-layer mutation
        window.dispatchEvent(new CustomEvent('odysseus:task-toggle', {
          detail: { taskId, projectId: projId, completed: willBeCompleted }
        }));
      } catch (err) {
        console.error('Failed to toggle task completion:', err);
        dot.classList.toggle('checked', !willBeCompleted);
        if (titleEl) titleEl.classList.toggle('completed', !willBeCompleted);
      }
    });
  });

  // Operations email draft bridge
  container.querySelectorAll('[data-draft-email]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const email = btn.dataset.draftEmail;
      const name = btn.dataset.draftName || 'Customer';
      const summary = btn.dataset.draftSummary || 'your inquiry';
      const subject = `Re: Bil Weekend Inquiry - ${name}`;
      const body = `Dear ${name},\n\nThank you for reaching out to Bil Weekend regarding ${summary}.\n\nBest regards,\nBil Weekend Operations Team`;

      // If email module compose modal exists, invoke it
      if (window.emailModule && window.emailModule.openCompose) {
        window.emailModule.openCompose({ to: email, subject, body });
      } else {
        // Fallback: trigger mailto or notification
        window.location.href = `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
      }
    });
  });

  // Open in Operations
  container.querySelectorAll('[data-open-ops]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (window.operationsModule && window.operationsModule.openOperations) {
        closeOverview();
        window.operationsModule.openOperations();
      }
    });
  });
}

function _escape(str) {
  return String(str || '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function _formatDate(isoStr) {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    if (isToday) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch (_) {
    return isoStr.substring(0, 10);
  }
}

/**
 * Open the Overview Hub modal.
 */
export function openOverview() {
  _open = true;
  const modal = _getModal();
  modal.classList.remove('hidden', 'modal-minimized');
  modal.style.display = 'flex';

  Modals.register('overview-modal', {
    railBtnId: 'rail-overview',
    sidebarBtnId: 'tool-overview-btn',
    closeFn: () => _doClose(),
    restoreFn: () => {},
  });

  _fetchOverviewData(false);
}

function _doClose() {
  Modals.unregister('overview-modal');
  if (_modal) _modal.remove();
  _modal = null;
  _open = false;
  _overviewData = null;
}

export function closeOverview() {
  _doClose();
}

export function isOverviewOpen() {
  return _open;
}

export function refreshOverview(force = true) {
  _fetchOverviewData(force);
}

// Global module export & Auto-wire setup
window.overviewModule = {
  openOverview,
  closeOverview,
  isOverviewOpen,
  refreshOverview,
  registerWidget,
};

// Wire rail and sidebar click events
document.addEventListener('DOMContentLoaded', () => {
  const railBtn = document.getElementById('rail-overview');
  if (railBtn) {
    railBtn.addEventListener('click', () => {
      if (!Modals.toggle('overview-modal')) {
        openOverview();
      }
    });
  }

  const sidebarBtn = document.getElementById('tool-overview-btn');
  if (sidebarBtn) {
    sidebarBtn.addEventListener('click', () => {
      if (!Modals.toggle('overview-modal')) {
        openOverview();
      }
    });
  }

  // Cross-layer mutation listener
  window.addEventListener('odysseus:task-toggle', () => {
    if (_open) _fetchOverviewData(false);
  });
  window.addEventListener('odysseus:state-mutation', () => {
    if (_open) _fetchOverviewData(false);
  });

  // Handle SPA deep link /overview
  if (window.location.pathname.toLowerCase() === '/overview') {
    setTimeout(openOverview, 200);
  }
});

export default {
  openOverview,
  closeOverview,
  isOverviewOpen,
  refreshOverview,
  registerWidget,
};
