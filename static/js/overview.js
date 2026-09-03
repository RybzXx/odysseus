// static/js/overview.js
/**
 * Executive Overview Hub — the WorkBench home view, and a standalone modal.
 *
 * Core Features:
 * - High-density Morning Briefing KPI banner.
 * - 7-Day Email Digest with multi-account filtering, date presets, and AI urgency badges.
 * - Responsive Active Projects Matrix: wide-screen multi-column checklists vs. compact accordions.
 * - Inbound Operations & Inquiries Radar across all 5 operational pipelines with Email Draft bridge.
 * - Multi-tier SWR (Stale-While-Revalidate) caching for instant sub-10ms loads.
 * - Strictly zero emojis; native Odysseus Feather/Lucide inline SVG iconography.
 * - Real-time cross-layer state synchronicity via DOM event bus.
 *
 * Under the WorkBench (SYSTEM_RECORD Rev Y) this file no longer owns a window.
 * It renders into a caller-supplied container and registers as the `home` view;
 * `openOverview()` survives as chrome wrapped around that same render path, so
 * there is one renderer whether the panels sit in a WorkBench layer or in the
 * standalone modal. Filter state lives per mounted instance rather than in
 * module scope, because two instances may now exist at once.
 */

import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';
import { registerView, navigate as workBenchNavigate } from './workbench.js';

/** container element -> render state. One entry per mounted instance. */
const _instances = new Map();

let _stylesInjected = false;

// The standalone modal, which is chrome around one mounted instance.
let _modal = null;
let _modalBody = null;
let _open = false;

/**
 * Per-instance render state.
 *
 * Inv: nothing here is module-level. A drilled-into layer that comes back must
 *      show the filters it had, and a second instance must not steal them.
 */
function _newState() {
  return {
    emailAccountFilter: 'all',
    emailDaysFilter: 7,
    emailUnreadOnly: false,
    opsFilterSource: 'all',
    expandedProjectIds: new Set(),
    data: null,
    loading: false,
  };
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
  layers: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>`,
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
    /* The view itself: a toolbar over a scrolling body, filling whatever
       container mounts it — a WorkBench layer or the standalone modal. */
    .overview-view {
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      font-family: var(--font-family, system-ui, sans-serif);
      color: var(--fg, #abb2bf);
    }
    .overview-toolbar {
      padding: 8px 16px;
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
      background: var(--bg, #282c34);
    }
    .overview-toolbar .overview-cache-status {
      font-size: 11px;
      opacity: 0.6;
      font-family: 'Fira Code', monospace;
      margin-right: auto;
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
      border-color: color-mix(in srgb, var(--status-error, #e06c75) 40%, transparent);
      background: color-mix(in srgb, var(--status-error, #e06c75) 4%, transparent);
    }
    /* KPI cards drill: emails to the digest, tasks to Projects, inquiries to
       Operations. Only the drillable ones take the affordance. */
    .overview-kpi-card[data-drill-view] {
      cursor: pointer;
      transition: border-color 0.15s ease, background 0.15s ease;
    }
    .overview-kpi-card[data-drill-view]:hover {
      border-color: rgba(255,255,255,0.25);
      background: rgba(255,255,255,0.03);
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
    /* Urgency binds one derived token per level; the badge shape is written
       once against it. Derived per theme by deriveStatusColors in theme.js,
       so an urgent email reads the same way on all sixteen themes without
       this file naming a colour. */
    .overview-urgency-badge {
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 2px 5px;
      border-radius: 3px;
      letter-spacing: 0.4px;
      background: color-mix(in srgb, var(--overview-urgency) 20%, transparent);
      color: var(--overview-urgency);
      border: 1px solid var(--overview-urgency);
    }
    .overview-urgency-badge.critical { --overview-urgency: var(--status-error, #e06c75); }
    .overview-urgency-badge.urgent   { --overview-urgency: var(--status-warn, #e5c07b); }
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
      border-color: color-mix(in srgb, var(--status-error, #e06c75) 40%, transparent);
      background: color-mix(in srgb, var(--status-error, #e06c75) 3%, transparent);
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

// ---------------------------------------------------------------------------
// View lifecycle — the WorkBench home
// ---------------------------------------------------------------------------

/**
 * Render the cockpit into `container`.
 *
 * Pre:  `container` is attached to the document and is not already mounted.
 * Post: the container holds a toolbar and a body; a briefing fetch is in
 *       flight; an instance state exists for the container.
 * Inv:  nothing outside `container` is written to — `document.body` is the
 *       caller's business, never this view's.
 */
export function mount(container, _params = {}) {
  if (_instances.has(container)) return;
  _injectStyles();

  const state = _newState();
  _instances.set(container, state);

  container.classList.add('overview-view');
  container.innerHTML = `
    <div class="overview-toolbar">
      <span class="overview-cache-status" data-cache-status></span>
      <button class="overview-btn" data-drill-organisers title="Open AI Work Organisers">
        ${ICONS.layers}
        <span>AI Organisers</span>
      </button>
      <button class="overview-btn" data-refresh-overview title="Refresh Dashboard">
        ${ICONS.refresh}
        <span>Refresh</span>
      </button>
    </div>
    <div class="overview-body" data-overview-body>
      <div class="overview-empty">Loading executive briefing...</div>
    </div>
  `;

  container.querySelector('[data-refresh-overview]').addEventListener('click', () => {
    _fetchOverviewData(container, true);
  });
  container.querySelector('[data-drill-organisers]').addEventListener('click', () => {
    _drill(container, 'organisers', {}, () => {
      if (window.openOrganisers) window.openOrganisers();
    });
  });

  // The overview payload is served from a 120s two-tier SWR cache whose DB
  // half survives a deploy. Opening the cockpit is exactly the moment a stale
  // briefing is most misleading, so the first read of a mount forces through.
  _fetchOverviewData(container, true);
}

/**
 * Discard the instance mounted in `container`.
 *
 * Post: no listener, timer or in-flight render can still write to the
 *       container — `_fetchOverviewData` checks membership before rendering,
 *       and every listener died with the innerHTML that carried it.
 */
export function unmount(container) {
  if (!_instances.has(container)) return;
  _instances.delete(container);
  container.innerHTML = '';
  container.classList.remove('overview-view');
}

/**
 * Drill from a cockpit row into a module.
 *
 * Inside a WorkBench layer this stacks a view; in the standalone modal it
 * falls back to the module's own opener, which is what keeps `openOverview()`
 * usable on its own.
 */
function _drill(container, viewId, params, legacyOpen) {
  if (container.closest('.wb-layer')) {
    workBenchNavigate(viewId, params);
    return;
  }
  if (typeof legacyOpen === 'function') legacyOpen();
}

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

/**
 * Fetch the briefing for one mounted instance and re-render it.
 *
 * Pre:  `container` is mounted.
 * Post: on success the instance holds fresh data and has re-rendered; on
 *       failure an unrendered instance shows the error and a rendered one
 *       keeps the data it had.
 */
async function _fetchOverviewData(container, forceRefresh = false) {
  const state = _instances.get(container);
  if (!state) return;

  state.loading = true;
  _updateCacheStatusBanner(container);
  try {
    const res = await fetch(
      `/api/overview?email_days=${state.emailDaysFilter}&force_refresh=${forceRefresh}&_=${Date.now()}`,
      { credentials: 'same-origin' },
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    // The instance may have been unmounted while the request was in flight.
    if (_instances.get(container) !== state) return;
    state.data = payload;
    _render(container);
  } catch (err) {
    console.error('Failed to load overview data:', err);
    if (_instances.get(container) !== state) return;
    const body = container.querySelector('[data-overview-body]');
    if (body && !state.data) {
      body.innerHTML = `<div class="overview-empty" style="color:var(--red,#e06c75)">Failed to load briefing: ${_escape(err.message)}</div>`;
    }
  } finally {
    if (_instances.get(container) === state) {
      state.loading = false;
      _updateCacheStatusBanner(container);
    }
  }
}

function _updateCacheStatusBanner(container) {
  const state = _instances.get(container);
  if (!state) return;
  const banner = container.querySelector('[data-cache-status]');
  if (!banner) return;

  if (state.loading) {
    banner.textContent = 'Updating...';
    return;
  }
  if (state.data && state.data.cached_at) {
    const timeStr = state.data.cached_at.substring(11, 16);
    banner.textContent = `Synced ${timeStr} UTC ${state.data.is_stale ? '(Revalidating)' : ''}`;
  }
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function _render(container) {
  const state = _instances.get(container);
  if (!state || !state.data) return;
  const body = container.querySelector('[data-overview-body]');
  if (!body) return;

  const kpis = state.data.kpis || {};
  const emailsData = state.data.email_digest || { accounts: [], emails: [] };
  const projectsData = state.data.projects_matrix || [];
  const opsData = state.data.operations_radar || { inquiries: [] };

  // Filter emails
  let filteredEmails = emailsData.emails || [];
  if (state.emailAccountFilter !== 'all') {
    filteredEmails = filteredEmails.filter(e => e.account_id === state.emailAccountFilter);
  }
  if (state.emailUnreadOnly) {
    filteredEmails = filteredEmails.filter(e => !e.read);
  }

  // Filter operations
  let filteredOps = opsData.inquiries || [];
  if (state.opsFilterSource !== 'all') {
    filteredOps = filteredOps.filter(i => i.source === state.opsFilterSource);
  }

  const daysLabel = state.emailDaysFilter === 1 ? 'Today' : `${state.emailDaysFilter}d`;

  body.innerHTML = `
    <!-- Top KPI Briefing Banner -->
    <div class="overview-kpi-grid">
      <div class="overview-kpi-card ${kpis.urgent_emails > 0 ? 'urgent' : ''}">
        <div class="overview-kpi-label">${ICONS.mail} Urgent Emails (${daysLabel})</div>
        <div class="overview-kpi-value">${kpis.urgent_emails || 0}</div>
        <div class="overview-kpi-sub">${kpis.unread_emails || 0} unread across ${emailsData.accounts.length || 1} accounts</div>
      </div>
      <div class="overview-kpi-card" data-drill-view="projects">
        <div class="overview-kpi-label">${ICONS.folder} Open Tasks</div>
        <div class="overview-kpi-value">${kpis.open_tasks || 0}</div>
        <div class="overview-kpi-sub">Across ${kpis.active_projects || 0} active workspaces</div>
      </div>
      <div class="overview-kpi-card ${kpis.overdue_inquiries > 0 ? 'urgent' : ''}" data-drill-view="operations">
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
              <select class="overview-select" data-email-account-select>
                <option value="all">All Accounts (${emailsData.accounts.length})</option>
                ${emailsData.accounts.map(a => `<option value="${a.id}" ${state.emailAccountFilter === a.id ? 'selected' : ''}>${a.name}</option>`).join('')}
              </select>
              <button class="overview-btn ${state.emailDaysFilter === 1 ? 'active' : ''}" data-days="1">Today</button>
              <button class="overview-btn ${state.emailDaysFilter === 3 ? 'active' : ''}" data-days="3">3d</button>
              <button class="overview-btn ${state.emailDaysFilter === 7 ? 'active' : ''}" data-days="7">7d</button>
              <label style="margin-left:auto;font-size:11px;display:flex;align-items:center;gap:4px;cursor:pointer;">
                <input type="checkbox" data-unread-toggle ${state.emailUnreadOnly ? 'checked' : ''}>
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
            <span>Operations &amp; Inquiries Radar</span>
          </div>
          <div class="overview-panel-body">
            <div class="overview-controls-row">
              <select class="overview-select" data-ops-source-select>
                <option value="all">All Channels</option>
                <option value="booking" ${state.opsFilterSource === 'booking' ? 'selected' : ''}>Registration</option>
                <option value="contact" ${state.opsFilterSource === 'contact' ? 'selected' : ''}>Contact</option>
                <option value="curated" ${state.opsFilterSource === 'curated' ? 'selected' : ''}>Curated</option>
                <option value="queue" ${state.opsFilterSource === 'queue' ? 'selected' : ''}>WhatsApp Queue</option>
              </select>
            </div>

            <div style="display:flex;flex-direction:column;gap:8px;max-height:300px;overflow-y:auto;">
              ${filteredOps.length === 0 ? '<div class="overview-empty">No recent operations inquiries.</div>' : ''}
              ${filteredOps.map(op => `
                <div class="overview-inquiry-item ${op.is_overdue ? 'overdue' : ''}">
                  <div class="overview-inquiry-header">
                    <span class="overview-source-badge">${_escape(op.source)}</span>
                    <strong style="color:#fff;">${_escape(op.name)}</strong>
                    <span style="font-size:11px;opacity:0.6;margin-left:auto;">${_escape(op.status)}</span>
                  </div>
                  <div style="font-size:12px;opacity:0.85;">${_escape(op.summary || 'Enquiry record')}</div>
                  ${op.is_overdue ? `<div style="color:var(--status-error,#e06c75);font-size:11px;display:flex;align-items:center;gap:4px;">${ICONS.alertCircle} Overdue action (${_escape(op.next_action_date)})</div>` : ''}
                  <div class="overview-inquiry-actions">
                    ${op.email ? `
                      <button class="overview-btn" data-draft-email="${_escape(op.email)}" data-draft-name="${_escape(op.name)}" data-draft-summary="${_escape(op.summary)}">
                        ${ICONS.send}
                        <span>Draft Reply</span>
                      </button>
                    ` : ''}
                    <button class="overview-btn" data-open-ops="${_escape(op.key)}" data-open-ops-name="${_escape(op.name)}" style="margin-left:auto;">
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
          <span>Active Projects &amp; Tasks Matrix</span>
        </div>
        <div class="overview-panel-body">
          <div class="overview-projects-container">
            ${projectsData.length === 0 ? '<div class="overview-empty">No active projects configured.</div>' : ''}
            ${projectsData.map(proj => {
              const completedCount = proj.tasks.filter(t => t.completed).length;
              const totalCount = proj.tasks.length;
              const percent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;
              const isExpanded = state.expandedProjectIds.has(proj.id);

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

  _bindEventListeners(container, body, state);
}

function _bindEventListeners(container, body, state) {
  // KPI cards that stand for a module
  body.querySelectorAll('[data-drill-view]').forEach(card => {
    card.addEventListener('click', () => {
      const viewId = card.dataset.drillView;
      _drill(container, viewId, {}, () => _legacyOpen(viewId, {}));
    });
  });

  // Email account selector
  const accSel = body.querySelector('[data-email-account-select]');
  if (accSel) {
    accSel.addEventListener('change', (e) => {
      state.emailAccountFilter = e.target.value;
      _render(container);
    });
  }

  // Email days preset buttons
  body.querySelectorAll('[data-days]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const days = parseInt(btn.dataset.days, 10) || 7;
      if (state.emailDaysFilter === days) return;
      state.emailDaysFilter = days;
      _fetchOverviewData(container, false);
    });
  });

  // Email item click to open in Email reader
  body.querySelectorAll('.overview-email-item').forEach(card => {
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
  const unreadToggle = body.querySelector('[data-unread-toggle]');
  if (unreadToggle) {
    unreadToggle.addEventListener('change', (e) => {
      state.emailUnreadOnly = e.target.checked;
      _render(container);
    });
  }

  // Operations source selector
  const opsSel = body.querySelector('[data-ops-source-select]');
  if (opsSel) {
    opsSel.addEventListener('change', (e) => {
      state.opsFilterSource = e.target.value;
      _render(container);
    });
  }

  // Project drilldown
  body.querySelectorAll('[data-drill-proj]').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      const projectId = el.dataset.drillProj;
      _drill(container, 'projects', { projectId }, () => _legacyOpen('projects', { projectId }));
    });
  });

  // Project accordion toggle
  body.querySelectorAll('[data-toggle-proj]').forEach(el => {
    el.addEventListener('click', () => {
      const projId = el.dataset.toggleProj;
      if (state.expandedProjectIds.has(projId)) {
        state.expandedProjectIds.delete(projId);
      } else {
        state.expandedProjectIds.add(projId);
      }
      _render(container);
    });
  });

  body.querySelectorAll('[data-expand-proj]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      state.expandedProjectIds.add(btn.dataset.expandProj);
      _render(container);
    });
  });

  // Task check-dot toggle
  body.querySelectorAll('.overview-check-dot').forEach(dot => {
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
  body.querySelectorAll('[data-draft-email]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const email = btn.dataset.draftEmail;
      const name = btn.dataset.draftName || 'Customer';
      const summary = btn.dataset.draftSummary || 'your inquiry';
      const subject = `Re: Bil Weekend Inquiry - ${name}`;
      const emailBody = `Dear ${name},\n\nThank you for reaching out to Bil Weekend regarding ${summary}.\n\nBest regards,\nBil Weekend Operations Team`;

      // If email module compose modal exists, invoke it
      if (window.emailModule && window.emailModule.openCompose) {
        window.emailModule.openCompose({ to: email, subject, body: emailBody });
      } else {
        // Fallback: trigger mailto or notification
        window.location.href = `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(emailBody)}`;
      }
    });
  });

  // Open in Operations. The record's name, not its key, is what carries:
  // Operations' search matches name/email/phone/operator, never the row key.
  body.querySelectorAll('[data-open-ops]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const query = btn.dataset.openOpsName || '';
      _drill(container, 'operations', { query }, () => _legacyOpen('operations', { query }));
    });
  });
}

/**
 * Open a module the pre-WorkBench way, closing the standalone Overview first.
 * Reached only from the standalone modal, which has no layer to stack onto.
 */
function _legacyOpen(viewId, params) {
  if (viewId === 'projects' && window.projectsModule && window.projectsModule.openProjects) {
    closeOverview();
    window.projectsModule.openProjects(params.projectId || null);
    return;
  }
  if (viewId === 'operations' && window.operationsModule && window.operationsModule.openOperations) {
    closeOverview();
    window.operationsModule.openOperations(params);
    return;
  }
  if (viewId === 'organisers' && window.openOrganisers) {
    window.openOrganisers();
  }
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

// ---------------------------------------------------------------------------
// Standalone modal — retained as the WorkBench's fallback, not its rival
// ---------------------------------------------------------------------------

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
        <button class="overview-btn" id="overview-minimize-btn" title="Minimize">_</button>
        <button class="overview-btn" id="overview-close-btn" title="Close (Esc)">${ICONS.close}</button>
      </div>
    </div>
    <div id="overview-body-container" style="flex:1;min-height:0;display:flex;flex-direction:column;"></div>
  `;

  document.body.appendChild(_modal);

  const header = _modal.querySelector('#overview-drag-header');
  makeWindowDraggable(_modal, { content: _modal, header });

  _modal.querySelector('#overview-close-btn').addEventListener('click', closeOverview);
  _modal.querySelector('#overview-minimize-btn').addEventListener('click', () => {
    Modals.minimize('overview-modal');
  });

  _modalBody = _modal.querySelector('#overview-body-container');
  return _modal;
}

/**
 * Open the Overview Hub as a standalone window.
 *
 * Kept working per the WorkBench reversibility guarantee: the same view is
 * mounted, only the chrome differs, so there is no second renderer to drift.
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

  mount(_modalBody, {});
}

function _doClose() {
  Modals.unregister('overview-modal');
  if (_modalBody) unmount(_modalBody);
  if (_modal) _modal.remove();
  _modal = null;
  _modalBody = null;
  _open = false;
}

export function closeOverview() {
  _doClose();
}

export function isOverviewOpen() {
  return _open;
}

/** Force a fresh briefing into every mounted instance. */
export function refreshOverview(force = true) {
  for (const container of _instances.keys()) {
    _fetchOverviewData(container, force);
  }
}

// ---------------------------------------------------------------------------
// Registration and wiring
// ---------------------------------------------------------------------------

registerView({
  id: 'home',
  title: 'Executive Overview',
  path: '/overview',
  icon: ICONS.dashboard,
  mount,
  unmount,
});

window.overviewModule = {
  openOverview,
  closeOverview,
  isOverviewOpen,
  refreshOverview,
  mount,
  unmount,
};

// Wire rail and sidebar click events
document.addEventListener('DOMContentLoaded', () => {
  const openCockpit = () => {
    if (window.workBench) {
      window.workBench.openWorkBench({ viewId: 'home' });
    } else {
      openOverview();
    }
  };

  const railBtn = document.getElementById('rail-overview');
  if (railBtn) {
    railBtn.addEventListener('click', () => {
      if (!Modals.toggle('workbench-modal') && !Modals.toggle('overview-modal')) {
        openCockpit();
      }
    });
  }

  const sidebarBtn = document.getElementById('tool-overview-btn');
  if (sidebarBtn) {
    sidebarBtn.addEventListener('click', () => {
      if (!Modals.toggle('workbench-modal') && !Modals.toggle('overview-modal')) {
        openCockpit();
      }
    });
  }

  // Cross-layer mutation listeners. These refresh every mounted instance,
  // which under the WorkBench includes a home layer sitting beneath a drill.
  window.addEventListener('odysseus:task-toggle', () => refreshOverview(false));
  window.addEventListener('odysseus:state-mutation', () => refreshOverview(false));

  // Deep link /overview is handled by app.js's _routeOpen map, which runs the
  // opener through startupShell's deferRouteOpener once module wiring has
  // settled. A second racing mechanism here (a bare 200ms timer) could fire
  // before or after that one and open the modal twice.
});

export default {
  openOverview,
  closeOverview,
  isOverviewOpen,
  refreshOverview,
  mount,
  unmount,
};
