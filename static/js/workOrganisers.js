// static/js/workOrganisers.js
/**
 * AI Work Organisers — Executive Taxonomy, Rule Engine & Cross-Module Backbone.
 *
 * Core Capabilities:
 * - High-level semantic categorisation derived from multi-account email traffic.
 * - AI Directives & prompt instructions for contextual agent triage.
 * - Granular matching rules (Accounts, Senders, Keywords, Domains).
 * - Live Email Stream preview with click-to-read integration into Odysseus Email Library.
 * - Direct bidirectional bindings to Tasks (ProjectTask) and Memories (Chroma lanes).
 * - Strictly zero emojis; native Odysseus Feather/Lucide inline SVG iconography.
 */

import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';
import { registerView } from './workbench.js';

let _open = false;
let _modal = null;
// The WorkBench layer this panel is mounted into, or null when it owns a
// window of its own. Set before _getModal() so the modal is built in place.
let _hostContainer = null;
let _organisers = [];
let _selectedId = null;
let _activeDetail = null; // cached full detail for _selectedId
let _activeTab = 'directives'; // 'directives' | 'emails' | 'tasks' | 'memories'
let _loading = false;
let _stylesInjected = false;
let _searchQuery = '';
let _availableAccounts = [];

// Inline Feather/Lucide SVG Icons (Zero Emojis)
const ICONS = {
  layers: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>`,
  briefcase: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>`,
  users: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
  globe: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>`,
  trendingUp: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>`,
  shield: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`,
  coffee: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8h1a4 4 0 0 1 0 8h-1"/><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/></svg>`,
  mail: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>`,
  checkSquare: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>`,
  brain: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-5.04z"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-5.04z"/></svg>`,
  sparkle: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></svg>`,
  plus: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>`,
  trash: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`,
  refresh: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>`,
  search: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`,
  close: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
};

function _getIconSvg(name) {
  switch (name) {
    case 'users': return ICONS.users;
    case 'globe': return ICONS.globe;
    case 'trending-up': return ICONS.trendingUp;
    case 'shield': return ICONS.shield;
    case 'coffee': return ICONS.coffee;
    case 'briefcase':
    default: return ICONS.briefcase;
  }
}

function _injectStyles() {
  if (_stylesInjected) return;
  _stylesInjected = true;
  const style = document.createElement('style');
  style.id = 'organisers-styles';
  style.textContent = `
    .organisers-modal {
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
      z-index: 10000;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      font-family: var(--font-family, system-ui, sans-serif);
      color: var(--fg, #abb2bf);
    }
    .organisers-modal.hidden {
      display: none !important;
    }
    .org-top-header {
      padding: 10px 16px;
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
      display: flex;
      align-items: center;
      gap: 12px;
      background: var(--bg, #282c34);
      user-select: none;
      flex-shrink: 0;
    }
    .org-layout {
      display: flex;
      flex: 1;
      overflow: hidden;
    }
    .org-sidebar {
      width: 340px;
      min-width: 300px;
      border-right: 1px solid var(--border, rgba(255,255,255,0.08));
      background: rgba(0,0,0,0.15);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .org-sidebar-header {
      padding: 12px 14px;
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.06));
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .org-search-bar {
      display: flex;
      align-items: center;
      gap: 6px;
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border, rgba(255,255,255,0.1));
      border-radius: 4px;
      padding: 4px 8px;
      font-size: 12px;
    }
    .org-search-bar input {
      background: transparent;
      border: none;
      outline: none;
      color: var(--fg, #fff);
      width: 100%;
      font-size: 12px;
    }
    .org-list {
      flex: 1;
      overflow-y: auto;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .org-card {
      padding: 10px 12px;
      border-radius: 6px;
      border: 1px solid var(--border, rgba(255,255,255,0.06));
      background: rgba(255,255,255,0.02);
      cursor: pointer;
      display: flex;
      flex-direction: column;
      gap: 6px;
      transition: background 0.15s, border-color 0.15s;
    }
    .org-card:hover {
      background: rgba(255,255,255,0.05);
      border-color: rgba(255,255,255,0.15);
    }
    .org-card.active {
      background: rgba(97, 175, 239, 0.08);
      border-color: var(--brand-color, #61afef);
    }
    .org-card-top {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .org-card-icon {
      width: 24px;
      height: 24px;
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .org-card-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--fg, #fff);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .org-card-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 11px;
      opacity: 0.7;
    }
    .org-badge {
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 1px 5px;
      border-radius: 3px;
      letter-spacing: 0.3px;
    }
    .org-badge.critical { background: rgba(224,108,117,0.2); color: #e06c75; }
    .org-badge.high { background: rgba(229,192,123,0.2); color: #e5c07b; }
    .org-badge.normal { background: rgba(97,175,239,0.15); color: #61afef; }
    .org-badge.low { background: rgba(152,195,121,0.15); color: #98c379; }

    /* Main Detail Pane */
    .org-main {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      background: rgba(0,0,0,0.05);
    }
    .org-main-header {
      padding: 14px 18px;
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .org-tabs-bar {
      display: flex;
      border-bottom: 1px solid var(--border, rgba(255,255,255,0.08));
      background: rgba(0,0,0,0.1);
      padding: 0 12px;
      overflow-x: auto;
      flex-wrap: nowrap;
      white-space: nowrap;
      -webkit-overflow-scrolling: touch;
      scrollbar-width: none;
    }
    .org-tabs-bar::-webkit-scrollbar {
      display: none;
    }
    .org-tab-btn {
      padding: 10px 12px;
      background: none;
      border: none;
      border-bottom: 2px solid transparent;
      color: var(--fg, #abb2bf);
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
      white-space: nowrap;
    }
    .org-tab-btn:hover { color: #fff; }
    .org-tab-btn.active {
      color: var(--brand-color, #61afef);
      border-bottom-color: var(--brand-color, #61afef);
    }
    .org-tab-content {
      flex: 1;
      overflow-y: auto;
      padding: 16px 20px;
    }
    .org-field-group {
      margin-bottom: 16px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .org-field-label {
      font-size: 12px;
      font-weight: 600;
      color: var(--fg, #dcdfe4);
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .org-field-sub {
      font-size: 11px;
      opacity: 0.6;
    }
    .org-input, .org-textarea, .org-select {
      background: rgba(0,0,0,0.25);
      border: 1px solid var(--border, rgba(255,255,255,0.12));
      border-radius: 4px;
      padding: 8px 10px;
      color: #fff;
      font-size: 13px;
      outline: none;
      font-family: inherit;
    }
    .org-textarea {
      min-height: 90px;
      line-height: 1.4;
      resize: vertical;
    }
    .org-input:focus, .org-textarea:focus, .org-select:focus {
      border-color: var(--brand-color, #61afef);
    }
    .org-email-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    .org-email-table th {
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid rgba(255,255,255,0.1);
      font-weight: 600;
      opacity: 0.7;
    }
    .org-email-table td {
      padding: 8px 10px;
      border-bottom: 1px solid rgba(255,255,255,0.04);
      vertical-align: middle;
    }
    .org-email-row {
      cursor: pointer;
    }
    .org-email-row:hover {
      background: rgba(255,255,255,0.04);
    }
    .org-task-item {
      padding: 8px 10px;
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 4px;
      margin-bottom: 6px;
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 13px;
    }
    .org-memory-item {
      padding: 10px 12px;
      background: rgba(255,255,255,0.02);
      border-left: 3px solid #61afef;
      border-radius: 0 4px 4px 0;
      margin-bottom: 8px;
      font-size: 12px;
      line-height: 1.4;
    }

    @media (max-width: 768px) {
      .organisers-modal {
        top: 0 !important;
        left: 0 !important;
        transform: none !important;
        width: 100vw !important;
        height: 100vh !important;
        height: 100dvh !important;
        max-height: 100dvh !important;
        border-radius: 0 !important;
        border: none !important;
        z-index: 100000 !important;
      }
      .org-layout {
        flex-direction: column !important;
      }
      .org-sidebar {
        width: 100% !important;
        min-width: 0 !important;
        max-height: 220px !important;
        border-right: none !important;
        border-bottom: 1px solid var(--border, rgba(255,255,255,0.1)) !important;
      }
      .org-main {
        flex: 1 !important;
        min-height: 0 !important;
      }
      .org-btn-text {
        display: none !important;
      }
    }
  `;
  document.head.appendChild(style);
}

function _esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function _getModal() {
  if (!_modal) {
    _injectStyles();
    _modal = document.createElement('div');
    _modal.id = 'organisers-modal';
    _modal.className = 'organisers-modal hidden';
    _modal.innerHTML = `
      <div class="org-top-header" id="org-drag-header">
        <div style="display:flex;align-items:center;gap:8px;font-weight:600;font-size:14px;color:#fff;">
          ${ICONS.layers}
          <span>AI Work Organisers</span>
        </div>
        <div style="margin-left:auto;display:flex;align-items:center;gap:8px;">
          <button class="overview-btn" id="org-seed-btn" title="Seed empirical categories from 14d email analysis">
            ${ICONS.refresh} <span class="org-btn-text">Seed Defaults</span>
          </button>
          <button class="overview-btn" id="org-new-btn" style="background:var(--brand-color,#61afef);color:#fff;border:none;">
            ${ICONS.plus} <span class="org-btn-text">New Organiser</span>
          </button>
          <button class="overview-btn" id="org-modal-close" title="Close">${ICONS.close}</button>
        </div>
      </div>
      <div style="padding:0;overflow:hidden;flex:1;display:flex;">
        <div class="org-layout" id="org-layout-container" style="flex:1;display:flex;overflow:hidden;">
          <div class="overview-loading" style="padding:40px;text-align:center;">Loading AI Work Organisers...</div>
        </div>
      </div>
    `;
    (_hostContainer || document.body).appendChild(_modal);
    const header = _modal.querySelector('#org-drag-header');
    // A layer is positioned by the shell; only a free-floating window drags.
    if (!_hostContainer) makeWindowDraggable(_modal, { header });

    _modal.querySelector('#org-modal-close').addEventListener('click', () => _doClose());
    _modal.querySelector('#org-seed-btn').addEventListener('click', () => _seedDefaults());
    _modal.querySelector('#org-new-btn').addEventListener('click', () => _createNewOrganiser());
  }
  return _modal;
}

// ================= API CALLS =================

async function _fetchOrganisers() {
  _loading = true;
  try {
    const [orgRes, accRes] = await Promise.all([
      fetch('/api/organisers', { credentials: 'same-origin' }),
      fetch('/api/email/accounts', { credentials: 'same-origin' }).catch(() => null),
    ]);
    if (!orgRes.ok) throw new Error(`HTTP ${orgRes.status}`);
    const data = await orgRes.json();
    _organisers = data.organisers || [];

    if (accRes && accRes.ok) {
      const accData = await accRes.json();
      _availableAccounts = accData.accounts || [];
    }

    if (_organisers.length > 0 && (!_selectedId || !_organisers.find(o => o.id === _selectedId))) {
      _selectedId = _organisers[0].id;
    }
    await _loadDetail(_selectedId);
    _render();
  } catch (err) {
    console.error('Failed to load organisers:', err);
  } finally {
    _loading = false;
  }
}

async function _loadDetail(id) {
  if (!id) {
    _activeDetail = null;
    return;
  }
  try {
    const res = await fetch(`/api/organisers/${encodeURIComponent(id)}`, { credentials: 'same-origin' });
    if (res.ok) {
      _activeDetail = await res.json();
    }
  } catch (err) {
    console.error('Failed to load organiser detail:', err);
  }
}

async function _saveOrganiser(id, payload) {
  try {
    const res = await fetch(`/api/organisers/${encodeURIComponent(id)}`, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await _fetchOrganisers();
  } catch (err) {
    alert(`Failed to save organiser: ${err.message}`);
  }
}

async function _deleteOrganiser(id) {
  if (!confirm('Are you sure you want to delete this Work Organiser?')) return;
  try {
    const res = await fetch(`/api/organisers/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      credentials: 'same-origin',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    _selectedId = null;
    await _fetchOrganisers();
  } catch (err) {
    alert(`Failed to delete organiser: ${err.message}`);
  }
}

async function _seedDefaults() {
  if (!confirm('Re-seed the 6 empirical categories derived from the 14-day email analysis?')) return;
  try {
    const res = await fetch('/api/organisers/seed-defaults', {
      method: 'POST',
      credentials: 'same-origin',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await _fetchOrganisers();
  } catch (err) {
    alert(`Failed to seed defaults: ${err.message}`);
  }
}

async function _createNewOrganiser() {
  const name = prompt('Enter a name for the new Work Organiser:');
  if (!name || !name.trim()) return;
  try {
    const res = await fetch('/api/organisers', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name.trim(),
        category_group: 'operations',
        icon: 'briefcase',
        priority: 'normal',
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _selectedId = data.organiser.id;
    await _fetchOrganisers();
  } catch (err) {
    alert(`Failed to create organiser: ${err.message}`);
  }
}

// ================= RENDERING =================

function _render() {
  if (!_modal) return;
  const layout = _modal.querySelector('#org-layout-container');
  if (!layout) return;

  const filteredOrgs = _organisers.filter(o => {
    if (!_searchQuery) return true;
    const q = _searchQuery.toLowerCase();
    return o.name.toLowerCase().includes(q) || (o.description || '').toLowerCase().includes(q) || o.category_group.toLowerCase().includes(q);
  });

  const selectedOrg = _organisers.find(o => o.id === _selectedId) || filteredOrgs[0];
  const detailData = _activeDetail && _activeDetail.organiser && _activeDetail.organiser.id === selectedOrg?.id ? _activeDetail : null;

  layout.innerHTML = `
    <!-- Left Sidebar: Categories List -->
    <div class="org-sidebar">
      <div class="org-sidebar-header">
        <div class="org-search-bar">
          ${ICONS.search}
          <input type="text" id="org-search-input" placeholder="Search workstreams..." value="${_esc(_searchQuery)}">
        </div>
      </div>
      <div class="org-list">
        ${filteredOrgs.length === 0 ? '<div style="padding:20px;text-align:center;font-size:12px;opacity:0.6;">No organisers match search.</div>' : ''}
        ${filteredOrgs.map(o => `
          <div class="org-card ${o.id === selectedOrg?.id ? 'active' : ''}" data-org-id="${o.id}">
            <div class="org-card-top">
              <div class="org-card-icon" style="background:${o.color}22;color:${o.color}">
                ${_getIconSvg(o.icon)}
              </div>
              <div style="flex:1;overflow:hidden;">
                <div class="org-card-title">${_esc(o.name)}</div>
              </div>
              <span class="org-badge ${o.priority}">${o.priority}</span>
            </div>
            <div class="org-card-meta">
              <span>${ICONS.mail} ${o.stats?.email_matches_14d || 0} emails</span>
              <span>•</span>
              <span>${ICONS.checkSquare} ${o.stats?.open_tasks || 0} tasks</span>
              <span>•</span>
              <span>${ICONS.brain} ${o.stats?.memories_count || 0} facts</span>
            </div>
          </div>
        `).join('')}
      </div>
    </div>

    <!-- Right Main Detail & Editor -->
    <div class="org-main">
      ${!selectedOrg ? `
        <div style="display:flex;align-items:center;justify-content:center;height:100%;opacity:0.5;font-size:13px;">
          Select or create a Work Organiser to inspect rules and AI directives.
        </div>
      ` : `
        <div class="org-main-header">
          <div class="org-card-icon" style="width:32px;height:32px;background:${selectedOrg.color}22;color:${selectedOrg.color}">
            ${_getIconSvg(selectedOrg.icon)}
          </div>
          <div style="flex:1;">
            <input type="text" id="org-edit-name" class="org-input" style="font-size:15px;font-weight:700;width:100%;background:transparent;border:none;padding:0;color:#fff;" value="${_esc(selectedOrg.name)}">
            <div style="font-size:11px;opacity:0.6;margin-top:2px;">Slug: <code>${selectedOrg.slug}</code> • Lane: <code>${selectedOrg.memory_lane || 'default'}</code></div>
          </div>
          <div style="display:flex;gap:8px;">
            <button class="overview-btn" id="org-save-btn" style="background:var(--brand-color,#61afef);color:#fff;border:none;">
              Save Changes
            </button>
            <button class="overview-btn" id="org-delete-btn" title="Delete organiser" style="color:#e06c75;">
              ${ICONS.trash}
            </button>
          </div>
        </div>

        <div class="org-tabs-bar">
          <button class="org-tab-btn ${_activeTab === 'directives' ? 'active' : ''}" data-tab="directives">
            ${ICONS.sparkle} AI Directives & Rules
          </button>
          <button class="org-tab-btn ${_activeTab === 'emails' ? 'active' : ''}" data-tab="emails">
            ${ICONS.mail} Live Matching Emails (${selectedOrg.stats?.email_matches_14d || 0})
          </button>
          <button class="org-tab-btn ${_activeTab === 'tasks' ? 'active' : ''}" data-tab="tasks">
            ${ICONS.checkSquare} Linked Tasks (${selectedOrg.stats?.open_tasks || 0})
          </button>
          <button class="org-tab-btn ${_activeTab === 'memories' ? 'active' : ''}" data-tab="memories">
            ${ICONS.brain} Semantic Memories (${selectedOrg.stats?.memories_count || 0})
          </button>
        </div>

        <div class="org-tab-content">
          ${_renderTabContent(selectedOrg, detailData)}
        </div>
      `}
    </div>
  `;

  _bindEvents(layout, selectedOrg);
}

function _renderTabContent(org, detail) {
  const rules = org.rules || {};
  const sendersStr = (rules.senders || []).join(', ');
  const keywordsStr = (rules.keywords || []).join(', ');
  const domainsStr = (rules.domains || []).join(', ');
  const targetAccounts = org.target_accounts || [];

  if (_activeTab === 'directives') {
    return `
      <div class="org-field-group">
        <label class="org-field-label">
          ${ICONS.sparkle} AI Assistant Mission & Directives
        </label>
        <div class="org-field-sub">Natural-language prompt instructions for the AI assistant when triaging, answering, and acting on items in this category.</div>
        <textarea id="org-edit-ai-instructions" class="org-textarea" rows="4">${_esc(org.ai_instructions || '')}</textarea>
      </div>

      <div class="org-grid-2col" style="display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:12px;">
        <div class="org-field-group">
          <label class="org-field-label">Domain Group</label>
          <select id="org-edit-group" class="org-select">
            <option value="operations" ${org.category_group === 'operations' ? 'selected' : ''}>Tour Operations & Bookings</option>
            <option value="strategy" ${org.category_group === 'strategy' ? 'selected' : ''}>Team Strategy & Product</option>
            <option value="partnerships" ${org.category_group === 'partnerships' ? 'selected' : ''}>B2B Partnerships & Suppliers</option>
            <option value="finance" ${org.category_group === 'finance' ? 'selected' : ''}>Financial Intelligence</option>
            <option value="tech" ${org.category_group === 'tech' ? 'selected' : ''}>Technical Infrastructure & Security</option>
            <option value="personal" ${org.category_group === 'personal' ? 'selected' : ''}>Personal & Logistics</option>
          </select>
        </div>
        <div class="org-field-group">
          <label class="org-field-label">Priority Level</label>
          <select id="org-edit-priority" class="org-select">
            <option value="critical" ${org.priority === 'critical' ? 'selected' : ''}>Critical (Immediate Escalation)</option>
            <option value="high" ${org.priority === 'high' ? 'selected' : ''}>High (Same-Day Response)</option>
            <option value="normal" ${org.priority === 'normal' ? 'selected' : ''}>Normal</option>
            <option value="low" ${org.priority === 'low' ? 'selected' : ''}>Low (Background / Informational)</option>
          </select>
        </div>
      </div>

      <div class="org-field-group" style="margin-top:10px;">
        <label class="org-field-label">${ICONS.mail} Sender Matching Patterns</label>
        <div class="org-field-sub">Comma-separated sender names or emails (e.g. <code>Adrian Matache, Mustafa Nabil, @rs.iq</code>).</div>
        <input type="text" id="org-edit-senders" class="org-input" value="${_esc(sendersStr)}">
      </div>

      <div class="org-field-group">
        <label class="org-field-label">${ICONS.search} Subject & Content Keywords</label>
        <div class="org-field-sub">Comma-separated keywords to capture (e.g. <code>quotation, proposal, rates, سوق العراق</code>).</div>
        <input type="text" id="org-edit-keywords" class="org-input" value="${_esc(keywordsStr)}">
      </div>

      <div class="org-field-group">
        <label class="org-field-label">${ICONS.globe} Domain Whitelist</label>
        <div class="org-field-sub">Comma-separated domains (e.g. <code>bilweekend.com, rs.iq, vercel.com</code>).</div>
        <input type="text" id="org-edit-domains" class="org-input" value="${_esc(domainsStr)}">
      </div>
    `;
  } else if (_activeTab === 'emails') {
    const matchedEmails = detail?.matching_emails || [];
    return `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
        <div style="font-size:12px;opacity:0.8;">Showing live messages matched over the past 14 days.</div>
      </div>
      ${matchedEmails.length === 0 ? `
        <div style="padding:40px;text-align:center;font-size:12px;opacity:0.6;">
          No emails match the current rules. Try adjusting senders or keywords in the Directives tab.
        </div>
      ` : `
        <table class="org-email-table">
          <thead>
            <tr>
              <th>Sender</th>
              <th>Subject</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            ${matchedEmails.map(em => `
              <tr class="org-email-row" data-email-uid="${em.uid}" data-email-account-id="${em.account_id}" data-email-folder="${em.folder}">
                <td style="font-weight:600;color:#fff;">${_esc(em.sender_name)}</td>
                <td>${_esc(em.subject)}</td>
                <td style="opacity:0.6;font-size:11px;">${_esc(em.date_display || em.date_iso?.substring(0,10))}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `}
    `;
  } else if (_activeTab === 'tasks') {
    const tasks = detail?.tasks || [];
    return `
      <div style="margin-bottom:12px;font-size:12px;opacity:0.8;">
        Active tasks linked to this workstream category.
      </div>
      ${tasks.length === 0 ? `
        <div style="padding:40px;text-align:center;font-size:12px;opacity:0.6;">
          No project tasks currently linked to this category.
        </div>
      ` : `
        <div style="display:flex;flex-direction:column;gap:6px;">
          ${tasks.map(t => `
            <div class="org-task-item">
              <input type="checkbox" ${t.completed ? 'checked' : ''} disabled>
              <div style="flex:1;${t.completed ? 'text-decoration:line-through;opacity:0.6;' : ''}">
                <div style="font-weight:500;color:#fff;">${_esc(t.title)}</div>
                ${t.due_date ? `<div style="font-size:11px;opacity:0.6;">Due: ${t.due_date}</div>` : ''}
              </div>
              <span class="org-badge ${t.priority || 'normal'}">${t.priority || 'normal'}</span>
            </div>
          `).join('')}
        </div>
      `}
    `;
  } else if (_activeTab === 'memories') {
    const mems = detail?.memories || [];
    return `
      <div style="margin-bottom:12px;font-size:12px;opacity:0.8;">
        Contextual facts and learned preferences preserved in lane <code>${org.memory_lane || 'default'}</code>.
      </div>
      ${mems.length === 0 ? `
        <div style="padding:40px;text-align:center;font-size:12px;opacity:0.6;">
          No memory notes stored in this lane yet. As the assistant interacts with you, it will record category insights here.
        </div>
      ` : `
        <div style="display:flex;flex-direction:column;gap:8px;">
          ${mems.map(m => `
            <div class="org-memory-item">
              <div style="color:#fff;">${_esc(m.content)}</div>
              ${m.tags ? `<div style="font-size:10px;opacity:0.5;margin-top:4px;">Tags: ${_esc(m.tags)}</div>` : ''}
            </div>
          `).join('')}
        </div>
      `}
    `;
  }
  return '';
}

function _bindEvents(layout, selectedOrg) {
  // Search filter
  const searchInput = layout.querySelector('#org-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      _searchQuery = e.target.value;
      _render();
    });
  }

  // Organiser card selection
  layout.querySelectorAll('.org-card').forEach(card => {
    card.addEventListener('click', async () => {
      const orgId = card.getAttribute('data-org-id');
      if (orgId !== _selectedId) {
        _selectedId = orgId;
        await _loadDetail(_selectedId);
        _render();
      }
    });
  });

  // Tab switching
  layout.querySelectorAll('.org-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _activeTab = btn.getAttribute('data-tab');
      _render();
    });
  });

  // Save changes
  const saveBtn = layout.querySelector('#org-save-btn');
  if (saveBtn && selectedOrg) {
    saveBtn.addEventListener('click', async () => {
      const nameInput = layout.querySelector('#org-edit-name');
      const aiInput = layout.querySelector('#org-edit-ai-instructions');
      const groupInput = layout.querySelector('#org-edit-group');
      const priorityInput = layout.querySelector('#org-edit-priority');
      const sendersInput = layout.querySelector('#org-edit-senders');
      const keywordsInput = layout.querySelector('#org-edit-keywords');
      const domainsInput = layout.querySelector('#org-edit-domains');

      const payload = {
        name: nameInput ? nameInput.value.trim() : selectedOrg.name,
        ai_instructions: aiInput ? aiInput.value.trim() : selectedOrg.ai_instructions,
        category_group: groupInput ? groupInput.value : selectedOrg.category_group,
        priority: priorityInput ? priorityInput.value : selectedOrg.priority,
        rules: {
          senders: sendersInput ? sendersInput.value.split(',').map(s => s.trim()).filter(Boolean) : (selectedOrg.rules?.senders || []),
          keywords: keywordsInput ? keywordsInput.value.split(',').map(k => k.trim()).filter(Boolean) : (selectedOrg.rules?.keywords || []),
          domains: domainsInput ? domainsInput.value.split(',').map(d => d.trim()).filter(Boolean) : (selectedOrg.rules?.domains || []),
        },
      };

      saveBtn.textContent = 'Saving...';
      await _saveOrganiser(selectedOrg.id, payload);
    });
  }

  // Delete button
  const deleteBtn = layout.querySelector('#org-delete-btn');
  if (deleteBtn && selectedOrg) {
    deleteBtn.addEventListener('click', () => _deleteOrganiser(selectedOrg.id));
  }

  // Email row click to open in Odysseus Email Library
  layout.querySelectorAll('.org-email-row').forEach(row => {
    row.addEventListener('click', () => {
      const uid = row.getAttribute('data-email-uid');
      const accountId = row.getAttribute('data-email-account-id');
      const folder = row.getAttribute('data-email-folder') || 'INBOX';
      if (window.openEmailLibrary) {
        window.openEmailLibrary({ folder, uid, accountId });
      }
    });
  });
}

// ================= MODAL LIFECYCLE =================

/**
 * Open the Organisers panel as a standalone window.
 *
 * @param {string} [organiserId] Select this organiser instead of the first,
 *        so a drill from the cockpit lands on the one the user clicked.
 */
export function openOrganisers(organiserId = null) {
  _open = true;
  // Defensive: this is also reachable as a bare click handler, which would
  // otherwise pass an Event where an id is expected.
  if (typeof organiserId === 'string' && organiserId) _selectedId = organiserId;
  const modal = _getModal();
  modal.classList.remove('hidden', 'modal-minimized');
  modal.style.display = 'flex';

  // On mobile screens, dismiss the sidebar overlay. Inside a WorkBench layer
  // the shell already owns the viewport, so the sidebar is not ours to touch.
  if (!_hostContainer && window.innerWidth < 768) {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.add('hidden');
    document.documentElement.classList.add('ody-sidebar-off');
  }

  if (!_hostContainer) {
    Modals.register('organisers-modal', {
      railBtnId: 'rail-organisers',
      sidebarBtnId: 'tool-organisers-btn',
      closeFn: () => _doClose(),
      restoreFn: () => {},
    });
  }

  _fetchOrganisers();
}

/**
 * Render the Organisers panel into a WorkBench layer.
 *
 * Pre:  `container` is an empty layer element.
 * Post: the panel is inside `container` with `params.organiserId` selected
 *       when given, and no window chrome of its own.
 * Inv:  the rule engine, directives and email preview are untouched.
 */
export function mount(container, params = {}) {
  _hostContainer = container;
  openOrganisers(params && params.organiserId ? params.organiserId : null);
}

export function unmount(_container) {
  _doClose();
  _hostContainer = null;
}

function _doClose() {
  Modals.unregister('organisers-modal');
  if (_modal) _modal.remove();
  _modal = null;
  _open = false;
}

export function closeOrganisers() {
  _doClose();
}

registerView({
  id: 'organisers',
  title: 'AI Work Organisers',
  path: '/organisers',
  mount,
  unmount,
  queryFromParams: (params) => (params && params.organiserId ? `organiser=${encodeURIComponent(params.organiserId)}` : ''),
  paramsFromQuery: (search) => ({ organiserId: search.get('organiser') || null }),
});

// Global window exposure
if (typeof window !== 'undefined') {
  window.openWorkOrganisers = openOrganisers;
  window.openOrganisers = openOrganisers;
  window.organisersModule = { openOrganisers, closeOrganisers, mount, unmount };
}

// Auto-wire navigation rail and sidebar buttons
function _bindLauncherButtons() {
  const railBtn = document.getElementById('rail-organisers');
  if (railBtn) {
    railBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!Modals.toggle('organisers-modal')) {
        openOrganisers();
      }
    });
  }
  const sidebarBtn = document.getElementById('tool-organisers-btn');
  if (sidebarBtn) {
    sidebarBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!Modals.toggle('organisers-modal')) {
        openOrganisers();
      }
    });
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _bindLauncherButtons);
} else {
  _bindLauncherButtons();
}
