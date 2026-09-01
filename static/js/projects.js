// static/js/projects.js
/**
 * Projects Module — Hybrid Project Workspace Hub for Odysseus.
 * Combines File-as-Spec (PROJECT.md) with SQLite indexing, full Google Keep-style Notes & To-Dos,
 * interactive multi-item checklists, viewable image lightboxes, document/PDF viewers,
 * file attachments, and cross-module link management (Operations, Email, Calendar, Docs).
 */

import { makeWindowDraggable } from './windowDrag.js';
import uiModule from './ui.js';
import markdownModule from './markdown.js';
import { spawnConfetti } from './compare/vote.js';

let _open = false;
let _modal = null;
let _projects = [];
let _currentProjectId = null;
let _currentProject = null;
let _projectNotes = [];
let _activeTab = 'overview'; // 'overview' | 'tasks' | 'docs' | 'links'
let _noteFilter = 'all'; // 'all' | 'pinned' | 'checklist' | 'note' | 'files'
let _noteSearchQuery = '';
let _composerExpanded = false;
let _composerType = 'note'; // 'note' | 'todo' | 'file'
let _composerColor = 'default';
let _composerPinned = false;
let _composerAttachments = [];
let _composerChecklistRows = [''];
let _composerTitle = '';
let _composerBody = '';
let _isEditingSummary = false;
let _overviewSubTab = 'overview'; // 'overview' | 'extended' | 'structure' | 'spec'
let _structureData = null;
let _isEditingSpec = false;
let _statusFilter = 'all'; // 'all' | 'active' | 'on-hold' | 'halted'
let _searchQuery = '';
let _availableModels = [];
let _selectedModel = null; // { mid, url, displayName, endpointName }
let _statusModalProject = null;
let _stylesInjected = false;

const NOTE_COLORS = [
  { key: 'default', label: 'Default', bg: 'var(--bg-elev, #222)', border: 'var(--border, #3a3a3a)' },
  { key: 'yellow', label: 'Yellow', bg: 'rgba(242, 194, 68, 0.16)', border: '#f2c244' },
  { key: 'green', label: 'Green', bg: 'rgba(92, 184, 92, 0.16)', border: '#5cb85c' },
  { key: 'cyan', label: 'Cyan', bg: 'rgba(23, 162, 184, 0.16)', border: '#17a2b8' },
  { key: 'blue', label: 'Blue', bg: 'rgba(74, 144, 226, 0.16)', border: '#4a90e2' },
  { key: 'amber', label: 'Amber', bg: 'rgba(232, 163, 61, 0.16)', border: '#e8a33d' },
  { key: 'rose', label: 'Rose', bg: 'rgba(235, 87, 87, 0.16)', border: '#eb5757' },
  { key: 'purple', label: 'Purple', bg: 'rgba(155, 81, 224, 0.16)', border: '#9b51e0' },
];

function _esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function _notifyToast(msg, isError = false) {
  if (typeof window !== 'undefined' && window.uiModule) {
    if (isError && window.uiModule.showError) window.uiModule.showError(msg);
    else if (window.uiModule.showToast) window.uiModule.showToast(msg);
  } else if (typeof uiModule !== 'undefined' && uiModule) {
    if (isError && uiModule.showError) uiModule.showError(msg);
    else if (uiModule.showToast) uiModule.showToast(msg);
  } else {
    console.log('[Projects]', msg);
  }
}

function _formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function _isImageMime(mime, filename = '') {
  if (mime && mime.startsWith('image/')) return true;
  return /\.(png|jpe?g|webp|gif|svg|bmp|ico)$/i.test(filename);
}

function _isPdfMime(mime, filename = '') {
  if (mime === 'application/pdf') return true;
  return /\.pdf$/i.test(filename);
}

function _injectStyles() {
  if (_stylesInjected) return;
  _stylesInjected = true;
  const style = document.createElement('style');
  style.id = 'projects-styles';
  style.textContent = `
    #projects-modal .proj-modal-content {
      width: min(1080px, 95vw);
      height: min(760px, 90vh);
      display: flex;
      flex-direction: column;
      background: var(--bg, #1a1a1a);
      color: var(--fg, #eee);
      border: 1px solid var(--border, #333);
      border-radius: 10px;
      box-shadow: 0 16px 40px rgba(0,0,0,0.5);
      overflow: hidden;
      position: relative;
    }
    #projects-modal .proj-header {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 16px;
      background: var(--bg-elev, #242424);
      border-bottom: 1px solid var(--border, #333);
      flex-wrap: wrap;
    }
    #projects-modal .proj-select {
      background: var(--input-bg, #1e1e1e);
      color: var(--fg, #eee);
      border: 1px solid var(--border, #444);
      border-radius: 6px;
      padding: 6px 10px;
      font-size: 13px;
      font-weight: 600;
      max-width: 240px;
    }
    #projects-modal .proj-pill {
      font-size: 11px;
      padding: 3px 8px;
      border-radius: 12px;
      font-weight: 500;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .proj-pill.active { background: rgba(46, 204, 113, 0.18); color: #2ecc71; border: 1px solid #2ecc71; }
    .proj-pill.on-hold, .proj-pill.paused { background: rgba(241, 196, 15, 0.18); color: #f1c40f; border: 1px solid #f1c40f; }
    .proj-pill.halted, .proj-pill.archived, .proj-pill.completed { background: rgba(235, 87, 87, 0.18); color: #eb5757; border: 1px solid #eb5757; }

    /* Landing Page Filter Bar & Model Selector */
    .proj-landing-toolbar {
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-bottom: 22px;
      background: var(--bg-elev, #222);
      border: 1px solid var(--border, #333);
      border-radius: 8px;
      padding: 12px 16px;
    }
    .proj-landing-controls {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      justify-content: space-between;
    }
    .proj-filter-pills {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .proj-filter-pill {
      background: transparent;
      color: var(--fg-muted, #999);
      border: 1px solid var(--border, #444);
      border-radius: 20px;
      padding: 4px 12px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }
    .proj-filter-pill:hover {
      background: rgba(255,255,255,0.06);
      color: var(--fg, #eee);
    }
    .proj-filter-pill.active {
      background: var(--accent, #e8a33d);
      color: #111;
      border-color: var(--accent, #e8a33d);
      font-weight: 600;
    }
    .proj-pill-count {
      font-size: 10.5px;
      background: rgba(0,0,0,0.25);
      padding: 1px 6px;
      border-radius: 10px;
    }
    .proj-filter-pill.active .proj-pill-count {
      background: rgba(0,0,0,0.2);
      color: #111;
    }

    .proj-search-input {
      flex: 1;
      min-width: 200px;
      background: var(--input-bg, #181818);
      border: 1px solid var(--border, #444);
      border-radius: 6px;
      padding: 6px 12px;
      color: var(--fg, #eee);
      font-size: 12.5px;
    }
    .proj-search-input:focus {
      outline: none;
      border-color: var(--accent, #e8a33d);
    }

    .proj-model-picker-wrap {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      color: var(--fg-muted, #888);
    }
    .proj-model-select {
      background: var(--input-bg, #181818);
      border: 1px solid var(--border, #444);
      border-radius: 6px;
      padding: 5px 10px;
      color: var(--fg, #eee);
      font-size: 12px;
      font-weight: 500;
      max-width: 260px;
      cursor: pointer;
    }
    .proj-model-select:focus {
      outline: none;
      border-color: var(--accent, #e8a33d);
    }

    /* Status Reason Banner on Cards */
    .proj-status-reason-banner {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 6px;
      margin: 10px 0;
      font-size: 12.5px;
      line-height: 1.4;
    }
    .proj-status-reason-banner.on-hold {
      background: rgba(241, 196, 15, 0.12);
      border: 1px solid rgba(241, 196, 15, 0.35);
      color: #f1c40f;
    }
    .proj-status-reason-banner.halted {
      background: rgba(235, 87, 87, 0.12);
      border: 1px solid rgba(235, 87, 87, 0.35);
      color: #eb5757;
    }

    /* Status Transition Modal */
    .proj-status-modal-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.65);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 2000;
      backdrop-filter: blur(2px);
    }
    .proj-status-modal-card {
      background: var(--bg-elev, #222);
      border: 1px solid var(--border, #444);
      border-radius: 10px;
      padding: 20px;
      width: min(480px, 92vw);
      box-shadow: 0 16px 40px rgba(0,0,0,0.6);
    }
    #toast, .toast {
      z-index: 100100 !important;
    }
    
    #projects-modal .proj-btn {
      background: var(--bg-elev, #2a2a2a);
      color: var(--fg, #eee);
      border: 1px solid var(--border, #444);
      border-radius: 6px;
      padding: 5px 10px;
      font-size: 12px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: all 0.15s ease;
    }
    #projects-modal .proj-btn:hover { background: var(--border, #3a3a3a); border-color: var(--accent, #e8a33d); }
    #projects-modal .proj-btn.primary { background: var(--accent, #e8a33d); color: #111; font-weight: 600; border-color: var(--accent, #e8a33d); }
    #projects-modal .proj-btn.primary:hover { opacity: 0.9; }
    #projects-modal .proj-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    #projects-modal .proj-btn:disabled:hover { background: var(--bg-elev, #2a2a2a); border-color: var(--border, #444); }

    #projects-modal .proj-tabs {
      display: flex;
      gap: 4px;
      padding: 8px 16px 0;
      background: var(--bg-elev, #242424);
      border-bottom: 1px solid var(--border, #333);
    }
    #projects-modal .proj-tab {
      padding: 8px 14px;
      border: 1px solid transparent;
      border-bottom: none;
      border-radius: 6px 6px 0 0;
      background: transparent;
      color: var(--fg-muted, #999);
      cursor: pointer;
      font-size: 12px;
      font-weight: 500;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    #projects-modal .proj-tab.active {
      background: var(--bg, #1a1a1a);
      color: var(--fg, #eee);
      border-color: var(--border, #333);
      font-weight: 600;
    }
    #projects-modal .proj-tab-badge {
      background: rgba(255,255,255,0.1);
      border-radius: 10px;
      padding: 1px 6px;
      font-size: 10px;
    }

    #projects-modal .proj-body {
      flex: 1;
      overflow-y: auto;
      padding: 18px;
    }

    /* Tab: Overview */
    .proj-overview-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
    .proj-progress-bar { background: var(--bg-elev, #242424); border-radius: 6px; height: 8px; width: 100%; overflow: hidden; margin-bottom: 16px; border: 1px solid var(--border, #333); }
    .proj-progress-fill { background: var(--accent, #e8a33d); height: 100%; transition: width 0.3s ease; }
    
    /* Overview 4-Tier Subtabs */
    .proj-subtabs {
      display: flex;
      gap: 6px;
      margin-bottom: 16px;
      background: var(--bg-elev, #222);
      padding: 4px;
      border-radius: 8px;
      border: 1px solid var(--border, #333);
      flex-wrap: wrap;
    }
    .proj-subtab {
      padding: 6px 12px;
      border-radius: 6px;
      border: none;
      background: transparent;
      color: var(--fg-muted, #999);
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }
    .proj-subtab:hover {
      color: var(--fg, #eee);
      background: rgba(255,255,255,0.06);
    }
    .proj-subtab.active {
      background: var(--accent, #e8a33d);
      color: #111;
      font-weight: 600;
    }

    .proj-markdown-content {
      background: var(--bg-elev, #202020);
      border: 1px solid var(--border, #333);
      border-radius: 8px;
      padding: 18px;
      line-height: 1.6;
      font-size: 13.5px;
    }
    .proj-markdown-content h1, .proj-markdown-content h2, .proj-markdown-content h3 {
      margin-top: 1.2em;
      margin-bottom: 0.6em;
      color: var(--fg, #eee);
    }
    .proj-markdown-content h1:first-child, .proj-markdown-content h2:first-child { margin-top: 0; }
    .proj-markdown-content pre {
      background: var(--input-bg, #141414);
      border: 1px solid var(--border, #333);
      border-radius: 6px;
      padding: 12px;
      overflow-x: auto;
    }
    .proj-markdown-content code {
      background: rgba(255,255,255,0.08);
      padding: 2px 5px;
      border-radius: 4px;
      font-size: 12px;
    }
    .proj-markdown-content table {
      width: 100%;
      border-collapse: collapse;
      margin: 14px 0;
    }
    .proj-markdown-content th, .proj-markdown-content td {
      border: 1px solid var(--border, #3a3a3a);
      padding: 8px 12px;
      font-size: 12.5px;
    }
    .proj-markdown-content th {
      background: var(--bg-elev, #262626);
      font-weight: 600;
    }

    .proj-summary-editor {
      width: 100%;
      height: 380px;
      background: var(--input-bg, #181818);
      color: var(--fg, #eee);
      border: 1px solid var(--border, #444);
      border-radius: 8px;
      padding: 12px;
      font-family: monospace;
      font-size: 12px;
      resize: vertical;
      line-height: 1.5;
    }

    /* File Topology Tree & Tech Cards */
    .proj-tree-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
      gap: 10px;
      margin: 14px 0;
    }
    .proj-tree-item {
      background: var(--bg-elev, #222);
      border: 1px solid var(--border, #333);
      border-radius: 6px;
      padding: 8px 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 12px;
    }
    .proj-tree-item.is-dir { border-left: 3px solid var(--accent, #e8a33d); }
    .proj-tree-item-name { display: flex; align-items: center; gap: 6px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .proj-tree-item-meta { font-size: 10.5px; color: var(--fg-muted, #888); }

    .proj-badge-pill {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      background: rgba(232, 163, 61, 0.15);
      color: var(--accent, #e8a33d);
      border: 1px solid rgba(232, 163, 61, 0.3);
      border-radius: 12px;
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 600;
    }

    /* Project Manifest Tasks */
    .proj-manifest-card {
      background: var(--bg-elev, #202020);
      border: 1px solid var(--border, #333);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 20px;
    }
    .proj-manifest-task-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin: 12px 0;
    }
    .proj-manifest-task-row {
      display: flex;
      align-items: center;
      gap: 10px;
      background: var(--bg, #1a1a1a);
      border: 1px solid var(--border, #333);
      border-radius: 6px;
      padding: 8px 12px;
      transition: background 0.15s;
    }
    .proj-manifest-task-row:hover { background: rgba(255,255,255,0.03); border-color: #444; }
    .proj-manifest-task-row.done .proj-manifest-task-text { text-decoration: line-through; color: var(--fg-muted, #777); opacity: 0.7; }
    .proj-manifest-task-checkbox {
      width: 16px;
      height: 16px;
      cursor: pointer;
      accent-color: var(--accent, #e8a33d);
    }
    .proj-manifest-task-text { flex: 1; font-size: 13px; color: var(--fg, #eee); }
    .proj-manifest-add-row {
      display: flex;
      gap: 8px;
      margin-top: 10px;
    }
    .proj-manifest-add-input {
      flex: 1;
      background: var(--input-bg, #181818);
      border: 1px solid var(--border, #444);
      border-radius: 6px;
      padding: 7px 12px;
      color: var(--fg, #eee);
      font-size: 12.5px;
    }
    .proj-manifest-add-input:focus { border-color: var(--accent, #e8a33d); outline: none; }

    /* Notes & To-Dos Composer */
    .proj-composer-compact {
      display: flex;
      align-items: center;
      gap: 10px;
      background: var(--bg-elev, #222);
      border: 1px solid var(--border, #3a3a3a);
      border-radius: 8px;
      padding: 9px 14px;
      cursor: pointer;
      margin-bottom: 16px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.2);
      transition: all 0.15s;
    }
    .proj-composer-compact:hover {
      border-color: var(--accent, #e8a33d);
      background: var(--input-bg, #1e1e1e);
    }
    .proj-composer-box {
      background: var(--bg-elev, #222);
      border: 1px solid var(--border, #3a3a3a);
      border-radius: 10px;
      padding: 12px 14px;
      margin-bottom: 18px;
      box-shadow: 0 4px 14px rgba(0,0,0,0.25);
      transition: border-color 0.2s;
    }
    .proj-composer-box:focus-within {
      border-color: color-mix(in srgb, var(--accent, #e8a33d) 60%, var(--border, #444));
    }
    .proj-composer-types {
      display: flex;
      gap: 6px;
      margin-bottom: 10px;
    }
    .proj-type-pill {
      background: var(--input-bg, #181818);
      border: 1px solid var(--border, #444);
      color: var(--fg-muted, #888);
      padding: 4px 10px;
      border-radius: 14px;
      font-size: 11px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: all 0.15s;
    }
    .proj-type-pill.active {
      background: var(--accent, #e8a33d);
      color: #111;
      border-color: var(--accent, #e8a33d);
      font-weight: 600;
    }
    .proj-comp-title {
      width: 100%;
      box-sizing: border-box;
      background: transparent;
      border: none;
      outline: none;
      font-size: 14px;
      font-weight: 600;
      color: var(--fg, #eee);
      padding: 4px 0 8px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      margin-bottom: 8px;
    }
    .proj-comp-content {
      width: 100%;
      box-sizing: border-box;
      background: transparent;
      border: none;
      outline: none;
      font-size: 13px;
      color: var(--fg, #eee);
      resize: vertical;
      min-height: 52px;
      font-family: inherit;
      line-height: 1.45;
    }
    .proj-comp-rows {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 10px;
    }
    .proj-comp-row-item {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .proj-comp-row-input {
      flex: 1;
      background: var(--input-bg, #181818);
      border: 1px solid var(--border, #333);
      border-radius: 5px;
      padding: 5px 8px;
      font-size: 12px;
      color: var(--fg, #eee);
      outline: none;
    }
    .proj-comp-row-input:focus {
      border-color: var(--accent, #e8a33d);
    }
    .proj-comp-dropzone {
      border: 2px dashed var(--border, #444);
      border-radius: 8px;
      padding: 20px;
      text-align: center;
      color: var(--fg-muted, #888);
      font-size: 12px;
      cursor: pointer;
      margin-bottom: 10px;
      transition: all 0.2s;
    }
    .proj-comp-dropzone.dragover {
      border-color: var(--accent, #e8a33d);
      background: rgba(232, 163, 61, 0.08);
      color: var(--fg, #eee);
    }
    .proj-comp-attachments {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 10px;
    }
    .proj-comp-att-chip {
      background: var(--input-bg, #181818);
      border: 1px solid var(--border, #444);
      border-radius: 6px;
      padding: 4px 8px;
      font-size: 11px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .proj-comp-att-chip .remove-att {
      cursor: pointer;
      color: #e74c3c;
      font-weight: bold;
    }
    .proj-composer-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid rgba(255,255,255,0.06);
    }
    .proj-comp-colors {
      display: flex;
      gap: 4px;
      align-items: center;
    }
    .proj-color-dot {
      width: 14px;
      height: 14px;
      border-radius: 50%;
      border: 1px solid rgba(255,255,255,0.2);
      cursor: pointer;
      transition: transform 0.15s;
    }
    .proj-color-dot:hover { transform: scale(1.25); }
    .proj-color-dot.active { transform: scale(1.3); border-color: #fff; box-shadow: 0 0 4px rgba(255,255,255,0.6); }

    /* Filter & Search Bar */
    .proj-filter-bar {
      display: flex;
      gap: 8px;
      margin-bottom: 14px;
      align-items: center;
      flex-wrap: wrap;
    }
    .proj-search-input {
      background: var(--input-bg, #181818);
      border: 1px solid var(--border, #444);
      border-radius: 6px;
      padding: 5px 10px;
      color: var(--fg, #eee);
      font-size: 12px;
      outline: none;
      width: 180px;
    }
    .proj-search-input:focus { border-color: var(--accent, #e8a33d); }

    /* Notes Cards Grid */
    .proj-notes-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
      gap: 14px;
    }
    .proj-section-title {
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: var(--fg-muted, #888);
      margin: 16px 0 8px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .proj-note-card {
      background: var(--bg-elev, #222);
      border: 1px solid var(--border, #333);
      border-radius: 10px;
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      transition: transform 0.15s, box-shadow 0.15s, border-color 0.2s;
      position: relative;
    }
    .proj-note-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 18px rgba(0,0,0,0.3);
      border-color: color-mix(in srgb, var(--accent, #e8a33d) 40%, var(--border, #333));
    }
    .proj-note-card.color-yellow { background: rgba(242, 194, 68, 0.12); border-color: rgba(242, 194, 68, 0.35); }
    .proj-note-card.color-green { background: rgba(92, 184, 92, 0.12); border-color: rgba(92, 184, 92, 0.35); }
    .proj-note-card.color-cyan { background: rgba(23, 162, 184, 0.12); border-color: rgba(23, 162, 184, 0.35); }
    .proj-note-card.color-blue { background: rgba(74, 144, 226, 0.12); border-color: rgba(74, 144, 226, 0.35); }
    .proj-note-card.color-amber { background: rgba(232, 163, 61, 0.12); border-color: rgba(232, 163, 61, 0.35); }
    .proj-note-card.color-rose { background: rgba(235, 87, 87, 0.12); border-color: rgba(235, 87, 87, 0.35); }
    .proj-note-card.color-purple { background: rgba(155, 81, 224, 0.12); border-color: rgba(155, 81, 224, 0.35); }

    .proj-note-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 6px;
    }
    .proj-note-title {
      font-weight: 600;
      font-size: 13.5px;
      color: var(--fg, #eee);
      line-height: 1.3;
      flex: 1;
      word-break: break-word;
    }
    .proj-note-toolbar {
      display: flex;
      align-items: center;
      gap: 3px;
      opacity: 0.4;
      transition: opacity 0.15s;
    }
    .proj-note-card:hover .proj-note-toolbar { opacity: 1; }
    .proj-card-btn {
      background: transparent;
      border: none;
      color: var(--fg-muted, #888);
      font-size: 12px;
      padding: 3px 5px;
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.15s;
    }
    .proj-card-btn:hover { background: rgba(255,255,255,0.1); color: var(--fg, #eee); }
    .proj-card-btn.pin-btn.active { color: var(--accent, #e8a33d); }
    .proj-card-btn.agent-btn:hover { color: var(--accent, #e8a33d); }
    .proj-card-btn.del-btn:hover { color: #e74c3c; }

    .proj-note-body-text {
      font-size: 12.5px;
      line-height: 1.45;
      color: color-mix(in srgb, var(--fg, #eee) 90%, transparent);
      white-space: pre-wrap;
      word-break: break-word;
    }

    /* Checklist items inside card */
    .proj-note-checklist {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .proj-note-check-item {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12.5px;
    }
    .proj-check-dot {
      width: 17px;
      height: 17px;
      border-radius: 50%;
      border: 1.75px solid color-mix(in srgb, var(--fg, #eee) 35%, transparent);
      background: var(--input-bg, #181818);
      flex-shrink: 0;
      position: relative;
      cursor: pointer;
      transition: all 0.15s cubic-bezier(0.34, 1.56, 0.64, 1);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0;
    }
    .proj-check-dot:hover { border-color: var(--accent, #e8a33d); transform: scale(1.15); }
    .proj-check-dot::after {
      content: '';
      position: absolute;
      left: 50%;
      top: 45%;
      width: 6px;
      height: 3px;
      border-left: 2px solid #fff;
      border-bottom: 2px solid #fff;
      transform: translate(-50%, -50%) rotate(-45deg) scale(0);
      transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    .proj-note-check-item.done .proj-check-dot {
      background: var(--accent, #e8a33d);
      border-color: var(--accent, #e8a33d);
      animation: proj-check-pop 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    .proj-note-check-item.done .proj-check-dot::after { transform: translate(-50%, -50%) rotate(-45deg) scale(1); }
    @keyframes proj-check-pop { 0% { transform: scale(1); } 40% { transform: scale(1.35); } 100% { transform: scale(1); } }
    .proj-check-text {
      flex: 1;
      cursor: text;
      border-radius: 4px;
      padding: 1px 4px;
      outline: none;
      word-break: break-word;
    }
    .proj-check-text:hover:not([contenteditable="true"]) { background: rgba(255,255,255,0.06); }
    .proj-check-text[contenteditable="true"] { background: var(--input-bg, #181818); box-shadow: 0 0 0 1.5px var(--accent, #e8a33d); }
    .proj-note-check-item.done .proj-check-text { text-decoration: line-through; color: var(--fg-muted, #777); opacity: 0.65; }

    /* Attached files & image previews */
    .proj-card-attachments {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-top: 6px;
      border-top: 1px solid rgba(255,255,255,0.06);
      padding-top: 6px;
    }
    .proj-att-img-preview {
      width: 100%;
      max-height: 160px;
      object-fit: cover;
      border-radius: 6px;
      cursor: zoom-in;
      border: 1px solid var(--border, #333);
      transition: transform 0.2s, opacity 0.2s;
    }
    .proj-att-img-preview:hover { opacity: 0.9; transform: scale(1.01); }
    .proj-att-file-chip {
      background: var(--input-bg, #181818);
      border: 1px solid var(--border, #444);
      border-radius: 6px;
      padding: 6px 10px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 11.5px;
      cursor: pointer;
      transition: all 0.15s;
    }
    .proj-att-file-chip:hover { border-color: var(--accent, #e8a33d); background: rgba(255,255,255,0.04); }
    .proj-att-file-info { display: flex; align-items: center; gap: 6px; overflow: hidden; }
    .proj-att-file-name { font-weight: 500; text-overflow: ellipsis; overflow: hidden; white-space: nowrap; }

    /* Lightbox Modal */
    #proj-lightbox-overlay {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.88);
      z-index: 99999;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      backdrop-filter: blur(4px);
    }
    #proj-lightbox-overlay .lightbox-img {
      max-width: 90vw;
      max-height: 80vh;
      border-radius: 8px;
      box-shadow: 0 12px 36px rgba(0,0,0,0.8);
      object-fit: contain;
    }
    #proj-lightbox-overlay .lightbox-bar {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-top: 14px;
      color: #eee;
    }

    /* Document Viewer Modal */
    #proj-doc-viewer-overlay {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.8);
      z-index: 99999;
      display: flex;
      align-items: center;
      justify-content: center;
      backdrop-filter: blur(4px);
    }
    #proj-doc-viewer-overlay .doc-viewer-card {
      width: min(920px, 92vw);
      height: min(80vh, 700px);
      background: var(--bg, #1a1a1a);
      border: 1px solid var(--border, #444);
      border-radius: 10px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 16px 40px rgba(0,0,0,0.6);
    }
    #proj-doc-viewer-overlay .doc-viewer-header {
      padding: 10px 16px;
      background: var(--bg-elev, #242424);
      border-bottom: 1px solid var(--border, #333);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    #proj-doc-viewer-overlay .doc-viewer-body {
      flex: 1;
      overflow: auto;
      padding: 16px;
      background: var(--input-bg, #181818);
    }

    /* Tab: Documents */
    .proj-docs-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
    .proj-doc-card { background: var(--bg-elev, #222); border: 1px solid var(--border, #333); border-radius: 8px; padding: 12px; cursor: pointer; transition: border-color 0.2s; }
    .proj-doc-card:hover { border-color: var(--accent, #e8a33d); }

    /* Tab: Linked Work */
    .proj-links-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
    .proj-link-card { background: var(--bg-elev, #222); border: 1px solid var(--border, #333); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 6px; }
    .proj-link-type-badge { font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--accent, #e8a33d); }
    .proj-link-target { font-family: monospace; font-size: 11px; color: var(--fg-muted, #999); }
  `;
  document.head.appendChild(style);
}

// ---------------------------------------------------------------------------
// Main Rendering Engine
// ---------------------------------------------------------------------------

function _renderModalSkeleton() {
  let modalEl = document.getElementById('projects-modal');
  if (modalEl) return modalEl;

  modalEl = document.createElement('div');
  modalEl.id = 'projects-modal';
  modalEl.className = 'modal hidden';
  modalEl.setAttribute('role', 'dialog');
  modalEl.setAttribute('aria-label', 'Projects Hub');

  modalEl.innerHTML = `
    <div class="modal-content proj-modal-content">
      <div class="proj-header modal-header">
        <select id="proj-select" class="proj-select" aria-label="Select Project"></select>
        <span id="proj-status-badge" class="proj-pill active">ACTIVE</span>
        <button id="proj-new-btn" class="proj-btn primary" title="Create Project">+ New Project</button>
        <button id="proj-sync-btn" class="proj-btn" title="Sync with disk PROJECT.md"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 21v-5h5"/></svg> Sync Disk</button>
        <button id="proj-agent-btn" class="proj-btn" title="Spawn Agent Session"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg> Agent Session</button>
        <div style="margin-left:auto; display:flex; gap:6px;">
          <button id="proj-close-btn" class="proj-btn close-btn" title="Close"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
        </div>
      </div>
      <div class="proj-tabs">
        <button class="proj-tab ${(_activeTab === 'overview') ? 'active' : ''}" data-tab="overview">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><path d="M8 14h8"/><path d="M8 18h4"/></svg> Overview & Summary
        </button>
        <button class="proj-tab ${(_activeTab === 'tasks') ? 'active' : ''}" data-tab="tasks">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> Notes & To-Dos <span id="proj-tasks-badge" class="proj-tab-badge">0</span>
        </button>
        <button class="proj-tab ${(_activeTab === 'docs') ? 'active' : ''}" data-tab="docs">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg> Documents & Files
        </button>
        <button class="proj-tab ${(_activeTab === 'links') ? 'active' : ''}" data-tab="links">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg> Linked Work <span id="proj-links-badge" class="proj-tab-badge">0</span>
        </button>
      </div>
      <div id="proj-body" class="proj-body">
        <div style="color:var(--fg-muted,#888); text-align:center; padding:40px;">Loading project...</div>
      </div>
    </div>
  `;

  document.body.appendChild(modalEl);
  _wireModalEvents(modalEl);
  return modalEl;
}

function _wireModalEvents(modalEl) {
  modalEl.addEventListener('click', (e) => { if (e.target === modalEl) closeProjects(); });
  modalEl.querySelector('#proj-close-btn')?.addEventListener('click', closeProjects);
  
  modalEl.querySelector('#proj-select')?.addEventListener('change', async (e) => {
    _currentProjectId = e.target.value;
    _updateActionButtonsEnabled();
    await _loadProjectDetail(_currentProjectId);
  });

  modalEl.querySelector('#proj-sync-btn')?.addEventListener('click', async () => {
    if (!_currentProjectId) return;
    try {
      const res = await fetch(`/api/projects/${_currentProjectId}/sync`, { method: 'POST' });
      if (!res.ok) throw new Error('Sync failed');
      _notifyToast('Project synced with disk!');
      await _loadProjectDetail(_currentProjectId);
    } catch (err) {
      _notifyToast('Disk sync error: ' + err.message, true);
    }
  });

  modalEl.querySelector('#proj-agent-btn')?.addEventListener('click', async () => {
    if (!_currentProjectId) return;
    try {
      _notifyToast('Spawning Project Agent Session...');
      const res = await fetch(`/api/projects/${_currentProjectId}/agent_session`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed to spawn agent session');
      const data = await res.json();
      closeProjects();
      if (window.sessionModule?.switchSession) {
        window.sessionModule.switchSession(data.session_id);
      }
    } catch (err) {
      _notifyToast('Agent spawn error: ' + err.message, true);
    }
  });

  modalEl.querySelector('#proj-new-btn')?.addEventListener('click', () => {
    _renderNewProjectInlineForm();
  });

  modalEl.querySelectorAll('.proj-tab').forEach((tabBtn) => {
    tabBtn.addEventListener('click', () => {
      _activeTab = tabBtn.getAttribute('data-tab');
      modalEl.querySelectorAll('.proj-tab').forEach((b) => b.classList.toggle('active', b === tabBtn));
      _renderActiveTabContent();
    });
  });

  const content = modalEl.querySelector('.proj-modal-content');
  const header = modalEl.querySelector('.proj-header');
  if (content && header) {
    makeWindowDraggable(modalEl, { content, header });
  }
}

// ---------------------------------------------------------------------------
// Data Fetching & State
// ---------------------------------------------------------------------------

function _statusRank(status) {
  const s = (status || 'active').toLowerCase().trim();
  if (s === 'active') return 0;
  if (['on-hold', 'on_hold', 'paused'].includes(s)) return 1;
  if (['halted', 'archived', 'stopped'].includes(s)) return 2;
  return 3;
}

async function _fetchProjectsList() {
  try {
    const res = await fetch('/api/projects');
    if (!res.ok) throw new Error('Failed to fetch projects list');
    const data = await res.json();
    _projects = data.projects || [];
    
    // Sort Active projects to the beginning
    _projects.sort((a, b) => {
      const rankDiff = _statusRank(a.status) - _statusRank(b.status);
      if (rankDiff !== 0) return rankDiff;
      const timeA = new Date(a.updated_at || a.created_at || 0).getTime();
      const timeB = new Date(b.updated_at || b.created_at || 0).getTime();
      return timeB - timeA;
    });

    const selectEl = document.getElementById('proj-select');
    if (selectEl) {
      selectEl.innerHTML = _projects.map((p) => `
        <option value="${_esc(p.id)}" ${p.id === _currentProjectId ? 'selected' : ''}>
          ${_esc(p.name)}
        </option>
      `).join('');
    }

    if ((!_currentProjectId || !_projects.some((p) => p.id === _currentProjectId)) && _projects.length > 0) {
      _currentProjectId = null; // Default to landing page
    } else if (_projects.length === 0) {
      _currentProjectId = null;
    }

    if (selectEl && _currentProjectId) {
      selectEl.value = _currentProjectId;
    }
  } catch (err) {
    _loggerError(err);
  }
}

async function _loadProjectDetail(projectId, silent = false) {
  if (!projectId) {
    _renderLandingPage();
    return;
  }
  
  // Show header controls when in a project
  const tabs = document.querySelector('.proj-tabs');
  if (tabs) tabs.style.display = 'flex';
  const newBtn = document.getElementById('proj-new-btn');
  if (newBtn) newBtn.style.display = 'none';
  const syncBtn = document.getElementById('proj-sync-btn');
  if (syncBtn) syncBtn.style.display = 'block';
  const agentBtn = document.getElementById('proj-agent-btn');
  if (agentBtn) agentBtn.style.display = 'block';
  const statusBadge = document.getElementById('proj-status-badge');
  if (statusBadge) statusBadge.style.display = 'inline-block';
  const select = document.getElementById('proj-select');
  if (select) select.style.display = 'none'; // Replaced by back button

  let backBtn = document.getElementById('proj-back-btn');
  if (!backBtn) {
    backBtn = document.createElement('button');
    backBtn.id = 'proj-back-btn';
    backBtn.className = 'proj-btn primary';
    backBtn.innerHTML = '⬅ All Projects';
    backBtn.style.marginRight = '12px';
    const header = document.querySelector('.proj-header');
    if (header) header.insertBefore(backBtn, header.firstChild);
    backBtn.addEventListener('click', () => {
      _currentProjectId = null;
      _renderLandingPage();
    });
  }
  backBtn.style.display = 'block';

  const body = document.getElementById('proj-body');
  if (!silent && body) {
    body.innerHTML = `<div style="color:var(--fg-muted,#888); text-align:center; padding:40px;">Loading project details...</div>`;
  }

  try {
    const [resProj, resNotes, resStructure] = await Promise.all([
      fetch(`/api/projects/${projectId}`),
      fetch(`/api/notes?project_id=${projectId}`).catch(() => ({ ok: false })),
      fetch(`/api/projects/${projectId}/structure`).catch(() => ({ ok: false })),
    ]);

    if (!resProj.ok) throw new Error('Failed to load project details');
    const data = await resProj.json();
    _currentProject = data.project;

    if (resNotes.ok) {
      const notesData = await resNotes.json();
      _projectNotes = notesData.notes || [];
    } else {
      _projectNotes = [];
    }

    if (resStructure.ok) {
      _structureData = await resStructure.json();
    } else {
      _structureData = null;
    }

    // Sync header
    _updateHeaderState();
    _renderActiveTabContent();
  } catch (err) {
    _loggerError(err);
    if (body) {
      body.innerHTML = `<div style="color:#e74c3c; text-align:center; padding:40px;">Error: ${_esc(err.message)}</div>`;
    }
  }
}

function _updateHeaderState() {
  const p = _currentProject;
  if (!p) return;

  const statusBadge = document.getElementById('proj-status-badge');
  if (statusBadge) {
    statusBadge.textContent = (p.status || 'ACTIVE').toUpperCase();
    statusBadge.className = `proj-pill ${p.status || 'active'}`;
  }

  const tasksBadge = document.getElementById('proj-tasks-badge');
  if (tasksBadge) {
    const totalItems = (_projectNotes.length > 0) ? _projectNotes.length : (p.task_total || 0);
    tasksBadge.textContent = totalItems;
  }

  const linksBadge = document.getElementById('proj-links-badge');
  if (linksBadge) {
    linksBadge.textContent = (p.links || []).length;
  }

  const selectEl = document.getElementById('proj-select');
  if (selectEl && selectEl.value !== p.id) {
    selectEl.value = p.id;
  }
}

function _updateActionButtonsEnabled() {
  const hasProj = !!_currentProjectId;
  ['proj-sync-btn', 'proj-agent-btn'].forEach((id) => {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = !hasProj;
  });
}

function _renderActiveTabContent() {
  const body = document.getElementById('proj-body');
  if (!body) return;
  if (!_currentProject) {
    _renderEmptyState();
    return;
  }

  if (_activeTab === 'overview') {
    _renderOverviewTab(body);
  } else if (_activeTab === 'tasks') {
    _renderTasksTab(body);
  } else if (_activeTab === 'docs') {
    _renderDocsTab(body);
  } else if (_activeTab === 'links') {
    _renderLinksTab(body);
  }
}

// ---------------------------------------------------------------------------
// Tab 1: Overview
// ---------------------------------------------------------------------------


async function _fetchAvailableModels() {
  if (_availableModels.length > 0) return _availableModels;
  try {
    const res = await fetch('/api/models', { credentials: 'same-origin' });
    if (!res.ok) return [];
    const data = await res.json();
    const items = data.items || [];
    const models = [];
    for (const ep of items) {
      if (ep.offline) continue;
      const displayNames = ep.models_display || ep.models || [];
      (ep.models || []).forEach((m, idx) => {
        models.push({
          mid: m,
          url: ep.url,
          endpointName: ep.endpoint_name || 'LLM',
          displayName: displayNames[idx] || m,
          category: ep.category || 'local',
        });
      });
    }
    _availableModels = models;
    if (!_selectedModel && models.length > 0) {
      const saved = localStorage.getItem('odysseus-project-summary-model');
      _selectedModel = models.find(m => m.mid === saved) || models[0];
    }
    return models;
  } catch (e) {
    console.warn('Failed to fetch models for projects:', e);
    return [];
  }
}

async function _renderLandingPage() {
  const container = document.getElementById('proj-body');
  if (!container) return;

  // Header tweaks for landing page
  const select = document.getElementById('proj-select');
  if (select) select.style.display = 'none';
  const tabs = document.querySelector('.proj-tabs');
  if (tabs) tabs.style.display = 'none';
  const newBtn = document.getElementById('proj-new-btn');
  if (newBtn) newBtn.style.display = 'block';
  const syncBtn = document.getElementById('proj-sync-btn');
  if (syncBtn) syncBtn.style.display = 'none';
  const agentBtn = document.getElementById('proj-agent-btn');
  if (agentBtn) agentBtn.style.display = 'none';
  const statusBadge = document.getElementById('proj-status-badge');
  if (statusBadge) statusBadge.style.display = 'none';

  let backBtn = document.getElementById('proj-back-btn');
  if (backBtn) backBtn.style.display = 'none';

  // Load models if not cached
  await _fetchAvailableModels();

  if (_projects.length === 0) {
    container.innerHTML = `<div style="padding:40px; text-align:center; color:var(--fg-muted);">No projects found. Create one to get started!</div>`;
    return;
  }

  // Calculate status counts
  const totalCount = _projects.length;
  const activeCount = _projects.filter(p => (p.status || 'active').toLowerCase() === 'active').length;
  const onHoldCount = _projects.filter(p => ['on-hold', 'on_hold', 'paused'].includes((p.status || '').toLowerCase())).length;
  const haltedCount = _projects.filter(p => ['halted', 'archived', 'stopped'].includes((p.status || '').toLowerCase())).length;

  // Filter projects
  const filteredProjects = _projects.filter(p => {
    const status = (p.status || 'active').toLowerCase();
    if (_statusFilter === 'active' && status !== 'active') return false;
    if (_statusFilter === 'on-hold' && !['on-hold', 'on_hold', 'paused'].includes(status)) return false;
    if (_statusFilter === 'halted' && !['halted', 'archived', 'stopped'].includes(status)) return false;

    if (_searchQuery.trim()) {
      const q = _searchQuery.toLowerCase();
      const matchName = (p.name || '').toLowerCase().includes(q);
      const matchSlug = (p.slug || '').toLowerCase().includes(q);
      const matchSummary = (p.agent_summary || p.description || '').toLowerCase().includes(q);
      const matchReason = (p.status_reason || '').toLowerCase().includes(q);
      return matchName || matchSlug || matchSummary || matchReason;
    }
    return true;
  });

  // Sort so Active projects are displayed first
  filteredProjects.sort((a, b) => {
    const rankDiff = _statusRank(a.status) - _statusRank(b.status);
    if (rankDiff !== 0) return rankDiff;
    const timeA = new Date(a.updated_at || a.created_at || 0).getTime();
    const timeB = new Date(b.updated_at || b.created_at || 0).getTime();
    return timeB - timeA;
  });

  // Build model select options
  let modelSelectHtml = '';
  if (_availableModels.length > 0) {
    modelSelectHtml = `
      <div class="proj-model-picker-wrap">
        <span>Model:</span>
        <select id="proj-model-select" class="proj-model-select">
          ${_availableModels.map(m => `
            <option value="${_esc(m.mid)}" ${_selectedModel && _selectedModel.mid === m.mid ? 'selected' : ''}>
              ${_esc(m.displayName)} (${_esc(m.endpointName)})
            </option>
          `).join('')}
        </select>
      </div>
    `;
  }

  const toolbarHtml = `
    <div class="proj-landing-toolbar">
      <div class="proj-landing-controls">
        <div class="proj-filter-pills">
          <button class="proj-filter-pill ${_statusFilter === 'all' ? 'active' : ''}" data-filter="all">
            All <span class="proj-pill-count">${totalCount}</span>
          </button>
          <button class="proj-filter-pill ${_statusFilter === 'active' ? 'active' : ''}" data-filter="active">
            Active <span class="proj-pill-count">${activeCount}</span>
          </button>
          <button class="proj-filter-pill ${_statusFilter === 'on-hold' ? 'active' : ''}" data-filter="on-hold">
            On-Hold <span class="proj-pill-count">${onHoldCount}</span>
          </button>
          <button class="proj-filter-pill ${_statusFilter === 'halted' ? 'active' : ''}" data-filter="halted">
            Halted <span class="proj-pill-count">${haltedCount}</span>
          </button>
        </div>

        ${modelSelectHtml}
      </div>

      <div style="display:flex; gap:10px; align-items:center;">
        <input id="proj-search-input" type="text" class="proj-search-input" placeholder="🔍 Search projects by title, slug, or summary..." value="${_esc(_searchQuery)}" />
        ${_searchQuery ? `<button id="proj-clear-search-btn" class="proj-btn" style="font-size:11px;">Clear</button>` : ''}
      </div>
    </div>
  `;

  let cardsHtml = '';
  if (filteredProjects.length === 0) {
    cardsHtml = `<div style="padding:40px; text-align:center; color:var(--fg-muted);">No projects match the selected filter.</div>`;
  } else {
    cardsHtml = filteredProjects.map(p => {
      let pinnedHtml = '';
      if (p.pinned_notes && p.pinned_notes.length > 0) {
        pinnedHtml = `
          <div class="proj-landing-pinned" style="margin-top: 12px; background: rgba(0,0,0,0.15); padding: 8px; border-radius: 6px;">
            <div style="font-size: 11px; font-weight: 600; color: var(--accent, #e8a33d); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">Urgent / Pinned</div>
            ${p.pinned_notes.map(n => `
              <div style="font-size: 13px; color: var(--fg); margin-bottom: 4px; padding-left: 12px; position: relative;">
                <span style="position: absolute; left: 0; top: 0; color: var(--accent, #e8a33d);">•</span>
                <b>${_esc(n.title || 'Pinned Note')}</b>: ${_esc((n.content || '').substring(0, 80))}...
              </div>
            `).join('')}
          </div>
        `;
      }

      const statusNormalized = (p.status || 'active').toLowerCase();
      let statusClass = 'active';
      let statusLabel = 'ACTIVE';
      if (['on-hold', 'on_hold', 'paused'].includes(statusNormalized)) {
        statusClass = 'on-hold';
        statusLabel = 'ON-HOLD';
      } else if (['halted', 'archived', 'stopped'].includes(statusNormalized)) {
        statusClass = 'halted';
        statusLabel = 'HALTED';
      }

      let reasonBannerHtml = '';
      if (p.status_reason && (statusClass === 'on-hold' || statusClass === 'halted')) {
        reasonBannerHtml = `
          <div class="proj-status-reason-banner ${statusClass}">
            <span>${statusClass === 'on-hold' ? '⚠️' : '⏹️'}</span>
            <div><b>${statusLabel} Reason:</b> ${_esc(p.status_reason)}</div>
          </div>
        `;
      }

      return `
        <div class="proj-landing-card" style="background: var(--bg-elev, #222); border: 1px solid var(--border, #333); border-radius: 8px; padding: 16px; margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <h2 style="margin: 0 0 4px 0; font-size: 18px;">${_esc(p.name)}</h2>
              <div style="font-size: 11px; color: var(--fg-muted); margin-bottom: 8px;">
                Slug: <code>${_esc(p.slug)}</code> &bull; Tasks: <strong>${p.task_completed || 0}/${p.task_total || 0}</strong>
              </div>
            </div>
            <div style="display:flex; align-items:center; gap:8px;">
              <span class="proj-pill ${statusClass}">${statusLabel}</span>
              <button class="proj-btn primary proj-open-btn" data-id="${_esc(p.id)}">Open Workspace</button>
            </div>
          </div>
          
          ${reasonBannerHtml}

          <div style="font-size: 13px; line-height: 1.5; color: var(--fg); margin: 10px 0;">
            ${_renderMarkdownSafe(p.agent_summary || p.description || 'No summary available.')}
          </div>
          
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:12px;">
            <button class="proj-btn proj-summarize-btn" data-id="${_esc(p.id)}" style="font-size: 11.5px;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px;"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
              Auto-Summarize
            </button>

            <button class="proj-btn proj-edit-status-btn" data-id="${_esc(p.id)}" style="font-size: 11.5px;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px;"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
              Edit Status
            </button>
          </div>

          ${pinnedHtml}
        </div>
      `;
    }).join('');
  }

  container.innerHTML = `
    <div style="padding: 24px; max-width: 860px; margin: 0 auto;">
      <h1 style="margin-top:0; font-size: 24px; margin-bottom: 16px;">Project Workspaces</h1>
      ${toolbarHtml}
      ${cardsHtml}
    </div>
  `;

  // Wire Filter Pills
  container.querySelectorAll('.proj-filter-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      _statusFilter = pill.getAttribute('data-filter');
      _renderLandingPage();
    });
  });

  // Wire Search Input
  const searchInput = container.querySelector('#proj-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      _searchQuery = e.target.value;
      _renderLandingPage();
      const nextInput = document.querySelector('#proj-search-input');
      if (nextInput) {
        nextInput.focus();
        nextInput.setSelectionRange(nextInput.value.length, nextInput.value.length);
      }
    });
  }

  container.querySelector('#proj-clear-search-btn')?.addEventListener('click', () => {
    _searchQuery = '';
    _renderLandingPage();
  });

  // Wire Model Select
  const modelSelect = container.querySelector('#proj-model-select');
  if (modelSelect) {
    modelSelect.addEventListener('change', (e) => {
      const mid = e.target.value;
      const found = _availableModels.find(m => m.mid === mid);
      if (found) {
        _selectedModel = found;
        localStorage.setItem('odysseus-project-summary-model', found.mid);
        _notifyToast(`Selected model: ${found.displayName}`);
      }
    });
  }

  // Wire Open Workspace Buttons
  container.querySelectorAll('.proj-open-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _currentProjectId = btn.getAttribute('data-id');
      _loadProjectDetail(_currentProjectId);
    });
  });

  // Wire Auto-Summarize Buttons
  container.querySelectorAll('.proj-summarize-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-id');
      const originalText = btn.innerHTML;
      btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin" style="margin-right:4px;"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg> Summarizing...`;
      btn.disabled = true;
      try {
        const payload = _selectedModel ? { model: _selectedModel.mid, endpoint_url: _selectedModel.url } : {};
        const res = await fetch(`/api/projects/${id}/summarize`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error('Summarization failed');
        const data = await res.json();
        if (data.llm_error) {
          _notifyToast(`AI summarize error (${data.llm_error}). Fell back to spec extractor.`, true);
        } else {
          _notifyToast(`Project summarized via ${data.model_used || 'AI'}!`);
        }
        await _fetchProjectsList();
        _renderLandingPage();
      } catch (err) {
        btn.innerHTML = originalText;
        btn.disabled = false;
        _notifyToast(err.message, true);
      }
    });
  });

  // Wire Edit Status Buttons
  container.querySelectorAll('.proj-edit-status-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.getAttribute('data-id');
      const project = _projects.find(p => p.id === id);
      if (project) {
        _openStatusEditModal(project);
      }
    });
  });
}

function _openStatusEditModal(project) {
  if (!project) return;
  const old = document.getElementById('proj-status-modal-overlay');
  if (old) old.remove();

  const currentStatus = (project.status || 'active').toLowerCase();
  const currentReason = project.status_reason || '';
  const projId = project.id || project.slug;

  const overlay = document.createElement('div');
  overlay.id = 'proj-status-modal-overlay';
  overlay.className = 'proj-status-modal-overlay';
  overlay.innerHTML = `
    <div class="proj-status-modal-card">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
        <h3 style="margin:0; font-size:16px;">Edit Status &bull; ${_esc(project.name)}</h3>
        <button id="proj-status-modal-close" class="proj-btn" style="border:none; padding:4px 8px;">✕</button>
      </div>

      <div style="margin-bottom:14px;">
        <label style="font-size:12px; font-weight:600; color:var(--fg-muted,#888); display:block; margin-bottom:8px; text-transform:uppercase;">Select Lifecycle Status</label>
        <div style="display:flex; gap:8px;">
          <label style="flex:1; cursor:pointer; background:var(--input-bg,#181818); border:1px solid var(--border,#444); border-radius:6px; padding:10px; display:flex; align-items:center; gap:8px; font-size:13px;">
            <input type="radio" name="proj_status_radio" value="active" ${currentStatus === 'active' ? 'checked' : ''} />
            <span style="color:#2ecc71; font-weight:600;">Active</span>
          </label>
          <label style="flex:1; cursor:pointer; background:var(--input-bg,#181818); border:1px solid var(--border,#444); border-radius:6px; padding:10px; display:flex; align-items:center; gap:8px; font-size:13px;">
            <input type="radio" name="proj_status_radio" value="on-hold" ${['on-hold', 'on_hold', 'paused'].includes(currentStatus) ? 'checked' : ''} />
            <span style="color:#f1c40f; font-weight:600;">On-Hold</span>
          </label>
          <label style="flex:1; cursor:pointer; background:var(--input-bg,#181818); border:1px solid var(--border,#444); border-radius:6px; padding:10px; display:flex; align-items:center; gap:8px; font-size:13px;">
            <input type="radio" name="proj_status_radio" value="halted" ${['halted', 'archived', 'stopped'].includes(currentStatus) ? 'checked' : ''} />
            <span style="color:#eb5757; font-weight:600;">Halted</span>
          </label>
        </div>
      </div>

      <div id="proj-reason-wrap" style="margin-bottom:16px; display:${currentStatus === 'active' ? 'none' : 'block'};">
        <label style="font-size:12px; font-weight:600; color:var(--fg-muted,#888); display:block; margin-bottom:6px; text-transform:uppercase;">Reason for Hold / Halt</label>
        <textarea id="proj-status-reason-input" class="proj-summary-editor" style="height:90px;" placeholder="Explain why this project is on hold or halted (blockers, dependencies, priorities)...">${_esc(currentReason)}</textarea>
      </div>

      <div style="display:flex; justify-content:flex-end; gap:8px;">
        <button id="proj-status-cancel-btn" class="proj-btn">Cancel</button>
        <button id="proj-status-save-btn" class="proj-btn primary">Save Status</button>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  const radios = overlay.querySelectorAll('input[name="proj_status_radio"]');
  const reasonWrap = overlay.querySelector('#proj-reason-wrap');
  const reasonInput = overlay.querySelector('#proj-status-reason-input');

  radios.forEach(r => {
    r.addEventListener('change', () => {
      if (r.value === 'active') {
        reasonWrap.style.display = 'none';
      } else {
        reasonWrap.style.display = 'block';
        if (reasonInput) reasonInput.focus();
      }
    });
  });

  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  overlay.querySelector('#proj-status-modal-close')?.addEventListener('click', () => overlay.remove());
  overlay.querySelector('#proj-status-cancel-btn')?.addEventListener('click', () => overlay.remove());

  overlay.querySelector('#proj-status-save-btn')?.addEventListener('click', async () => {
    const selectedRadio = overlay.querySelector('input[name="proj_status_radio"]:checked');
    const newStatus = selectedRadio ? selectedRadio.value : 'active';
    const newReason = reasonInput ? reasonInput.value.trim() : null;
    const saveBtn = overlay.querySelector('#proj-status-save-btn');

    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving...';
    }

    try {
      const payload = {
        status: newStatus,
        status_reason: newStatus === 'active' ? null : (newReason || 'No reason specified'),
      };

      const res = await fetch(`/api/projects/${projId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `Failed to update status (HTTP ${res.status})`);
      }

      const resData = await res.json();
      const updatedProject = resData.project || {};

      // Instantly mutate in-memory state
      project.status = updatedProject.status || newStatus;
      project.status_reason = updatedProject.status_reason !== undefined ? updatedProject.status_reason : payload.status_reason;

      const pIdx = _projects.findIndex(p => p.id === project.id || p.slug === project.slug);
      if (pIdx !== -1) {
        _projects[pIdx].status = project.status;
        _projects[pIdx].status_reason = project.status_reason;
      }
      if (_currentProject && (_currentProject.id === project.id || _currentProject.slug === project.slug)) {
        _currentProject.status = project.status;
        _currentProject.status_reason = project.status_reason;
      }

      overlay.remove();
      _notifyToast(`Status updated to ${newStatus.toUpperCase()}!`);
      
      await _fetchProjectsList();

      if (_currentProjectId) {
        const body = document.getElementById('proj-body');
        if (body) _renderOverviewTab(body);
      } else {
        _renderLandingPage();
      }
    } catch (err) {
      console.error('Failed to update project status:', err);
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save Status';
      }
      _notifyToast(err.message, true);
    }
  });
}

function _renderMarkdownSafe(text) {
  if (!text || !text.trim()) return '<div style="color:var(--fg-muted,#888); font-style:italic;">No content recorded.</div>';
  if (markdownModule && markdownModule.mdToHtml) {
    try {
      return markdownModule.mdToHtml(text, { shortcodes: false });
    } catch (e) {
      console.warn('Markdown parse error:', e);
    }
  }
  return `<pre style="white-space:pre-wrap; font-family:inherit;">${_esc(text)}</pre>`;
}

function _renderOverviewTab(container) {
  const p = _currentProject;
  if (!p) return;
  const progress = p.progress || 0;
  const struct = _structureData || {};
  const sections = struct.sections || {};

  const statusNormalized = (p.status || 'active').toLowerCase();
  let reasonBannerHtml = '';
  if (p.status_reason && ['on-hold', 'on_hold', 'paused', 'halted', 'archived'].includes(statusNormalized)) {
    const isHold = ['on-hold', 'on_hold', 'paused'].includes(statusNormalized);
    reasonBannerHtml = `
      <div class="proj-status-reason-banner ${isHold ? 'on-hold' : 'halted'}" style="margin-bottom:14px;">
        <span>${isHold ? '⚠️' : '⏹️'}</span>
        <div><b>${isHold ? 'ON-HOLD' : 'HALTED'} Reason:</b> ${_esc(p.status_reason)}</div>
      </div>
    `;
  }

  // 1. Header & Progress Bar
  let html = `
    <div class="proj-overview-header">
      <div>
        <h2 style="margin:0 0 4px;">${_esc(p.name)}</h2>
        <div style="color:var(--fg-muted,#888); font-size:12px; display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
          <span>Status: <strong style="text-transform:uppercase;">${_esc(p.status || 'active')}</strong></span> &bull;
          <span>Slug: <code>${_esc(p.slug)}</code></span> &bull; 
          <span>Priority: <strong>${_esc(p.priority || 'normal')}</strong></span> &bull;
          <span>Folder: <code>${_esc(struct.folder_path || p.folder_path || 'data/projects/' + p.slug)}</code></span>
        </div>
      </div>
      <div style="display:flex; gap:6px;">
        <button id="proj-edit-status-header-btn" class="proj-btn" title="Edit Status"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> Edit Status</button>
        <button id="proj-edit-manifest-btn" class="proj-btn" title="Edit Raw Manifest"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> ${_isEditingSummary ? 'Close Editor' : 'Edit Manifest'}</button>
      </div>
    </div>

    <div style="margin-bottom:14px;">
      <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
        <span>Progress: ${p.task_completed || 0}/${p.task_total || 0} tasks completed</span>
        <strong>${progress}%</strong>
      </div>
      <div class="proj-progress-bar">
        <div class="proj-progress-fill" style="width: ${progress}%;"></div>
      </div>
    </div>
    ${reasonBannerHtml}
  `;

  // If user clicked Edit Manifest, show full editor
  if (_isEditingSummary) {
    html += `
      <div style="background:var(--bg-elev,#222); border:1px solid var(--border,#333); border-radius:8px; padding:16px; margin-bottom:16px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <h3 style="margin:0; font-size:14px;">Edit PROJECT.md Manifest (YAML + Markdown)</h3>
          <div style="display:flex; gap:8px;">
            <button id="proj-cancel-summary-btn" class="proj-btn">Cancel</button>
            <button id="proj-save-summary-btn" class="proj-btn primary">Save & Sync to Disk</button>
          </div>
        </div>
        <textarea id="proj-summary-textarea" class="proj-summary-editor">${_esc(p.content || '')}</textarea>
      </div>
    `;
    container.innerHTML = html;

    container.querySelector('#proj-cancel-summary-btn')?.addEventListener('click', () => {
      _isEditingSummary = false;
      _renderOverviewTab(container);
    });

    container.querySelector('#proj-edit-manifest-btn')?.addEventListener('click', () => {
      _isEditingSummary = false;
      _renderOverviewTab(container);
    });

    container.querySelector('#proj-save-summary-btn')?.addEventListener('click', async () => {
      const text = container.querySelector('#proj-summary-textarea')?.value;
      try {
        const res = await fetch(`/api/projects/${p.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: text }),
        });
        if (!res.ok) throw new Error('Save failed');
        _isEditingSummary = false;
        uiModule.showToast('PROJECT.md updated and synced!');
        await _loadProjectDetail(p.id);
      } catch (err) {
        uiModule.showError('Save error: ' + err.message);
      }
    });
    return;
  }

  // 2. 4-Tier Sub-Tabs Navigation
  html += `
    <div class="proj-subtabs">
      <button class="proj-subtab ${_overviewSubTab === 'overview' ? 'active' : ''}" data-subtab="overview">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg> 1. Overview & Goals
      </button>
      <button class="proj-subtab ${_overviewSubTab === 'extended' ? 'active' : ''}" data-subtab="extended">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg> 2. Extended Look & Architecture
      </button>
      <button class="proj-subtab ${_overviewSubTab === 'structure' ? 'active' : ''}" data-subtab="structure">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> 3. Detailed Structure & Files
      </button>
      <button class="proj-subtab ${_overviewSubTab === 'spec' ? 'active' : ''}" data-subtab="spec">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg> 4. Spec File (${_esc(struct.spec_source || 'SPEC.md')})
      </button>
    </div>
  `;

  // 3. Sub-Tab Content Rendering
  if (_overviewSubTab === 'overview') {
    const overviewMd = sections.overview || p.description || '*No executive summary provided.*';
    html += `
      <div class="proj-markdown-content">
        ${_renderMarkdownSafe(overviewMd)}
      </div>
    `;
  } else if (_overviewSubTab === 'extended') {
    const tech = struct.tech || {};
    let techBadgesHtml = '';
    if (tech.npm_package || (tech.dependencies && tech.dependencies.length > 0)) {
      techBadgesHtml += `
        <div style="margin-bottom:14px; background:var(--bg,#181818); border:1px solid var(--border,#333); border-radius:6px; padding:12px;">
          <div style="font-size:11px; font-weight:600; text-transform:uppercase; color:var(--accent,#e8a33d); margin-bottom:8px;">Detected Node.js / Web Stack</div>
          <div style="display:flex; gap:6px; flex-wrap:wrap;">
            ${tech.npm_package ? `<span class="proj-badge-pill">📦 ${tech.npm_package}</span>` : ''}
            ${(tech.dependencies || []).map(d => `<span class="proj-badge-pill">${_esc(d)}</span>`).join('')}
          </div>
        </div>
      `;
    }
    if (tech.python_requirements && tech.python_requirements.length > 0) {
      techBadgesHtml += `
        <div style="margin-bottom:14px; background:var(--bg,#181818); border:1px solid var(--border,#333); border-radius:6px; padding:12px;">
          <div style="font-size:11px; font-weight:600; text-transform:uppercase; color:var(--accent,#e8a33d); margin-bottom:8px;">Python Environment Packages</div>
          <div style="display:flex; gap:6px; flex-wrap:wrap;">
            ${tech.python_requirements.map(r => `<span class="proj-badge-pill">🐍 ${_esc(r)}</span>`).join('')}
          </div>
        </div>
      `;
    }

    const extendedMd = sections.extended || '## System Architecture\n\nComponent workflows, services, and integration parameters are managed in this workspace.';
    html += `
      <div class="proj-markdown-content">
        ${techBadgesHtml}
        ${_renderMarkdownSafe(extendedMd)}
      </div>
    `;
  } else if (_overviewSubTab === 'structure') {
    const tree = struct.tree || [];
    const keyFiles = struct.key_files || [];
    const tech = struct.tech || {};

    let scriptsHtml = '';
    if (tech.scripts && Object.keys(tech.scripts).length > 0) {
      scriptsHtml = `
        <div style="margin-bottom:16px;">
          <div style="font-size:12px; font-weight:600; color:var(--accent,#e8a33d); margin-bottom:6px; text-transform:uppercase;">NPM Execution Scripts</div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            ${Object.entries(tech.scripts).map(([k, v]) => `
              <div style="background:var(--bg,#181818); border:1px solid var(--border,#333); border-radius:6px; padding:6px 10px; font-size:11.5px;">
                <code>npm run ${k}</code> &rarr; <span style="color:var(--fg-muted,#888);">${_esc(v)}</span>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }

    let keyFilesHtml = '';
    if (keyFiles.length > 0) {
      keyFilesHtml = `
        <div style="margin-bottom:16px;">
          <div style="font-size:12px; font-weight:600; color:var(--accent,#e8a33d); margin-bottom:6px; text-transform:uppercase;">Key Documentation & Configuration</div>
          <div style="display:flex; gap:6px; flex-wrap:wrap;">
            ${keyFiles.map(kf => `<span class="proj-badge-pill">📄 ${_esc(kf)}</span>`).join('')}
          </div>
        </div>
      `;
    }

    let treeHtml = '';
    if (tree.length > 0) {
      treeHtml = `
        <div>
          <div style="font-size:12px; font-weight:600; color:var(--accent,#e8a33d); margin-bottom:6px; text-transform:uppercase;">Workspace File Tree (${tree.length} top-level entries)</div>
          <div class="proj-tree-grid">
            ${tree.map(t => `
              <div class="proj-tree-item ${t.is_dir ? 'is-dir' : ''}">
                <div class="proj-tree-item-name">
                  <span>${t.is_dir ? '📁' : '📄'}</span>
                  <span>${_esc(t.name)}</span>
                </div>
                <div class="proj-tree-item-meta">
                  ${t.is_dir ? (t.children + ' items') : _formatBytes(t.size)}
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }

    const structureMd = sections.structure ? `<div style="margin-top:16px;">${_renderMarkdownSafe(sections.structure)}</div>` : '';

    html += `
      <div class="proj-markdown-content">
        ${keyFilesHtml}
        ${scriptsHtml}
        ${treeHtml}
        ${structureMd}
      </div>
    `;
  } else if (_overviewSubTab === 'spec') {
    const specMd = struct.spec_content || p.content || '# Specification\n\n*No formal spec file detected.*';
    html += `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
        <span style="font-size:12px; color:var(--fg-muted,#888);">Source: <code>${_esc(struct.spec_source || 'SPEC.md')}</code></span>
        <button id="proj-toggle-spec-edit-btn" class="proj-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> ${_isEditingSpec ? 'Preview Spec' : 'Edit Spec'}</button>
      </div>

      ${_isEditingSpec ? `
        <textarea id="proj-spec-textarea" class="proj-summary-editor">${_esc(specMd)}</textarea>
        <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:10px;">
          <button id="proj-cancel-spec-btn" class="proj-btn">Cancel</button>
          <button id="proj-save-spec-btn" class="proj-btn primary">Save Spec</button>
        </div>
      ` : `
        <div class="proj-markdown-content">
          ${_renderMarkdownSafe(specMd)}
        </div>
      `}
    `;
  }

  container.innerHTML = html;

  // Wire Subtabs switching
  container.querySelectorAll('.proj-subtab').forEach(btn => {
    btn.addEventListener('click', () => {
      _overviewSubTab = btn.getAttribute('data-subtab');
      _renderOverviewTab(container);
    });
  });

  // Wire Edit Status Header Button
  container.querySelector('#proj-edit-status-header-btn')?.addEventListener('click', () => {
    _openStatusEditModal(p);
  });

  // Wire Edit Manifest Button
  container.querySelector('#proj-edit-manifest-btn')?.addEventListener('click', () => {
    _isEditingSummary = !_isEditingSummary;
    _renderOverviewTab(container);
  });

  // Wire Spec Edit Toggle & Save
  container.querySelector('#proj-toggle-spec-edit-btn')?.addEventListener('click', () => {
    _isEditingSpec = !_isEditingSpec;
    _renderOverviewTab(container);
  });

  container.querySelector('#proj-cancel-spec-btn')?.addEventListener('click', () => {
    _isEditingSpec = false;
    _renderOverviewTab(container);
  });

  container.querySelector('#proj-save-spec-btn')?.addEventListener('click', async () => {
    const text = container.querySelector('#proj-spec-textarea')?.value;
    try {
      const res = await fetch(`/api/projects/${p.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text }),
      });
      if (!res.ok) throw new Error('Spec save failed');
      _isEditingSpec = false;
      _notifyToast('Spec saved and synced!');
      await _loadProjectDetail(p.id);
    } catch (err) {
      _notifyToast('Spec save error: ' + err.message, true);
    }
  });
}

// ---------------------------------------------------------------------------
// Tab 2: Full Notes, Checklists & Viewable Attachments
// ---------------------------------------------------------------------------

async function _uploadAndAttachFile(file) {
  const fd = new FormData();
  fd.append('files', file);
  const res = await fetch('/api/upload', { method: 'POST', body: fd });
  if (!res.ok) throw new Error(`Upload failed for ${file.name}`);
  const data = await res.json();
  const item = (data.files && data.files[0]) ? data.files[0] : (data.uploaded && data.uploaded[0]) || data;
  return {
    id: item.id,
    filename: file.name || item.name || 'attachment',
    mime_type: file.type || item.mime || 'application/octet-stream',
    size: file.size || item.size || 0,
    url: `/api/upload/${item.id}`,
  };
}

function _openImageLightbox(url, title = 'Image Preview') {
  const old = document.getElementById('proj-lightbox-overlay');
  if (old) old.remove();

  const overlay = document.createElement('div');
  overlay.id = 'proj-lightbox-overlay';
  overlay.innerHTML = `
    <img src="${_esc(url)}" class="lightbox-img" alt="${_esc(title)}" />
    <div class="lightbox-bar">
      <span style="font-weight:600; font-size:13px;">${_esc(title)}</span>
      <a href="${_esc(url)}" download="${_esc(title)}" class="proj-btn" style="text-decoration:none;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Download</a>
      <button id="lightbox-copy-btn" class="proj-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg> Copy Link</button>
      <button id="lightbox-close-btn" class="proj-btn close-btn" style="background:#e74c3c; color:#fff; border:none;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> Close</button>
    </div>
  `;

  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  overlay.querySelector('#lightbox-close-btn')?.addEventListener('click', () => overlay.remove());
  overlay.querySelector('#lightbox-copy-btn')?.addEventListener('click', () => {
    navigator.clipboard.writeText(window.location.origin + url);
    _notifyToast('Copied image URL to clipboard!');
  });

  document.body.appendChild(overlay);
}

function _openDocumentViewer(url, title = 'Document Viewer', mime = '') {
  const old = document.getElementById('proj-doc-viewer-overlay');
  if (old) old.remove();

  const isPdf = _isPdfMime(mime, title);
  const overlay = document.createElement('div');
  overlay.id = 'proj-doc-viewer-overlay';

  overlay.innerHTML = `
    <div class="doc-viewer-card">
      <div class="doc-viewer-header">
        <div style="font-weight:600; font-size:13.5px; display:flex; align-items:center; gap:8px;">
          <span>${isPdf ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 15h6"/><path d="M9 11h6"/></svg>' : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>'}</span>
          <span>${_esc(title)}</span>
        </div>
        <div style="display:flex; gap:8px;">
          <a href="${_esc(url)}" download="${_esc(title)}" class="proj-btn" style="text-decoration:none;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Download</a>
          <button id="doc-viewer-close-btn" class="proj-btn close-btn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
        </div>
      </div>
      <div class="doc-viewer-body" id="doc-viewer-body">
        ${isPdf ? `<iframe src="${_esc(url)}" style="width:100%; height:100%; border:none; min-height:480px;"></iframe>` : `<div style="text-align:center; padding:40px; color:var(--fg-muted,#888);">Loading document contents...</div>`}
      </div>
    </div>
  `;

  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  overlay.querySelector('#doc-viewer-close-btn')?.addEventListener('click', () => overlay.remove());

  document.body.appendChild(overlay);

  if (!isPdf) {
    fetch(url)
      .then((res) => res.text())
      .then((text) => {
        const bodyEl = overlay.querySelector('#doc-viewer-body');
        if (bodyEl) {
          bodyEl.innerHTML = `<pre style="white-space:pre-wrap; font-family:monospace; font-size:12px; line-height:1.5; color:var(--fg,#eee); margin:0;">${_esc(text)}</pre>`;
        }
      })
      .catch((err) => {
        const bodyEl = overlay.querySelector('#doc-viewer-body');
        if (bodyEl) bodyEl.innerHTML = `<div style="color:#e74c3c; padding:20px;">Could not load document: ${_esc(err.message)}</div>`;
      });
  }
}

function _renderTasksTab(container) {
  const p = _currentProject;
  if (!p) return;

  const manifestTasks = p.tasks || [];
  const manifestCompletedCount = manifestTasks.filter(t => t.completed).length;

  // Filter notes
  let visibleNotes = _projectNotes.filter((n) => {
    if (_noteFilter === 'pinned') return n.pinned;
    if (_noteFilter === 'checklist') return n.note_type === 'checklist';
    if (_noteFilter === 'note') return n.note_type === 'note';
    if (_noteFilter === 'files') return Array.isArray(n.attachments) && n.attachments.length > 0;
    return true;
  });

  if (_noteSearchQuery.trim()) {
    const q = _noteSearchQuery.toLowerCase().trim();
    visibleNotes = visibleNotes.filter((n) => {
      const matchTitle = (n.title || '').toLowerCase().includes(q);
      const matchContent = (n.content || '').toLowerCase().includes(q);
      const matchItems = Array.isArray(n.items) && n.items.some((it) => (it.text || '').toLowerCase().includes(q));
      return matchTitle || matchContent || matchItems;
    });
  }

  const pinnedNotes = visibleNotes.filter((n) => n.pinned);
  const otherNotes = visibleNotes.filter((n) => !n.pinned);

  container.innerHTML = `
    <!-- 1. Official Project Manifest Tasks (synced with PROJECT.md) -->
    <div class="proj-manifest-card">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <h3 style="margin:0; font-size:14px; display:flex; align-items:center; gap:6px;">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          Project Tasks <span style="font-size:11.5px; color:var(--fg-muted,#888); font-weight:normal;">(${manifestCompletedCount}/${manifestTasks.length} done &bull; synced to PROJECT.md)</span>
        </h3>
      </div>

      ${manifestTasks.length === 0 ? `
        <div style="color:var(--fg-muted,#888); font-size:12px; padding:6px 0; font-style:italic;">
          No checklist tasks defined in PROJECT.md yet. Add one below to sync it to disk!
        </div>
      ` : `
        <div class="proj-manifest-task-list">
          ${manifestTasks.map(t => `
            <div class="proj-manifest-task-row ${t.completed ? 'done' : ''}" data-task-id="${_esc(t.id)}">
              <input type="checkbox" class="proj-manifest-task-checkbox" ${t.completed ? 'checked' : ''} data-task-id="${_esc(t.id)}" />
              <span class="proj-manifest-task-text">${_esc(t.title)}</span>
              <button class="proj-card-btn del-btn proj-manifest-del-btn" data-task-id="${_esc(t.id)}" title="Delete task from PROJECT.md">🗑️</button>
            </div>
          `).join('')}
        </div>
      `}

      <div class="proj-manifest-add-row">
        <input type="text" id="proj-manifest-new-input" class="proj-manifest-add-input" placeholder="+ Add a new task to PROJECT.md (Press Enter to save)..." />
        <button id="proj-manifest-new-btn" class="proj-btn primary">+ Add Task</button>
      </div>
    </div>

    <!-- 2. Workspace Sticky Notes & Ad-hoc Checklists -->
    <div style="font-size:13px; font-weight:600; color:var(--fg-muted,#888); text-transform:uppercase; letter-spacing:0.6px; margin: 18px 0 10px;">
      Workspace Notes & Scratchpad
    </div>

    <!-- Comprehensive Quick-Add Composer -->
    ${!_composerExpanded ? `
      <div class="proj-composer-compact" id="proj-composer-compact" title="Click to add note or checklist">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--accent,#e8a33d); flex-shrink:0;">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        <span style="color:var(--fg-muted,#888); font-size:13px;">Take a note, create a checklist, or attach files...</span>
        <div style="margin-left:auto; display:flex; gap:6px;">
          <button type="button" class="proj-card-btn" data-mode="todo" title="New checklist"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg></button>
          <button type="button" class="proj-card-btn" data-mode="note" title="New note"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg></button>
          <button type="button" class="proj-card-btn" data-mode="file" title="Attach file"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg></button>
        </div>
      </div>
    ` : `
      <div class="proj-composer-box">
        <div class="proj-composer-types">
          <button type="button" class="proj-type-pill ${_composerType === 'note' ? 'active' : ''}" data-type="note"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> Note</button>
          <button type="button" class="proj-type-pill ${_composerType === 'todo' ? 'active' : ''}" data-type="todo"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg> Checklist</button>
          <button type="button" class="proj-type-pill ${_composerType === 'file' ? 'active' : ''}" data-type="file"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg> Attach File</button>
        </div>

        <input id="proj-comp-title-input" type="text" class="proj-comp-title" placeholder="${_composerType === 'todo' ? 'Checklist Title (e.g. Sprint Launch Tasks)...' : 'Note Title (e.g. Architecture Decisions)...'}" value="${_esc(_composerTitle)}" />

        ${_composerType === 'note' ? `
          <textarea id="proj-comp-content-input" class="proj-comp-content" placeholder="Take a note, write specifications, or paste references..."></textarea>
        ` : ''}

        ${_composerType === 'todo' ? `
          <div id="proj-comp-checklist-rows" class="proj-comp-rows">
            ${_composerChecklistRows.map((row, idx) => `
              <div class="proj-comp-row-item">
                <span class="proj-check-dot" style="cursor:default;"></span>
                <input type="text" class="proj-comp-row-input" data-idx="${idx}" placeholder="Checklist item (Press Enter for next)..." value="${_esc(row)}" />
              </div>
            `).join('')}
          </div>
        ` : ''}

        ${_composerType === 'file' ? `
          <div id="proj-comp-dropzone" class="proj-comp-dropzone">
            <div style="margin-bottom:6px;"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="opacity:0.7;"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg></div>
            <div style="font-weight:600; margin-bottom:4px;">Drag & Drop files here or click to browse</div>
            <div style="color:var(--fg-muted,#888); font-size:11px;">Supports Images, PDFs, Documents, Code files, Audio</div>
            <input type="file" id="proj-comp-file-input" multiple style="display:none;" />
          </div>
        ` : ''}

        <!-- Pending Attachments Chips -->
        ${_composerAttachments.length > 0 ? `
          <div class="proj-comp-attachments">
            ${_composerAttachments.map((att, idx) => `
              <div class="proj-comp-att-chip">
                <span>${_isImageMime(att.mime_type, att.filename) ? '🖼️' : '📄'}</span>
                <span>${_esc(att.filename)} (${_formatBytes(att.size)})</span>
                <span class="remove-att" data-idx="${idx}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></span>
              </div>
            `).join('')}
          </div>
        ` : ''}

        <div class="proj-composer-footer">
          <div class="proj-comp-colors">
            <button type="button" id="proj-comp-pin-btn" class="proj-card-btn ${_composerPinned ? 'pin-btn active' : ''}" title="${_composerPinned ? 'Unpin' : 'Pin to top'}">📌</button>
            <label class="proj-card-btn" title="Add file attachment" style="cursor:pointer;">
              📎
              <input type="file" id="proj-comp-extra-file" multiple style="display:none;" />
            </label>
            <span style="font-size:11px; color:var(--fg-muted,#888); margin-left:6px;">Color:</span>
            ${NOTE_COLORS.map((c) => `
              <div class="proj-color-dot ${c.key === _composerColor ? 'active' : ''}" data-color="${c.key}" style="background:${c.border};" title="${c.label}"></div>
            `).join('')}
          </div>
          <div style="display:flex; gap:6px;">
            <button type="button" id="proj-comp-close-btn" class="proj-btn">Close</button>
            <button id="proj-comp-save-btn" class="proj-btn primary">+ Save Item</button>
          </div>
        </div>
      </div>
    `}

    <!-- Filter & Search Bar -->
    <div class="proj-filter-bar">
      <input type="text" id="proj-note-search" class="proj-search-input" placeholder="Search notes & tasks..." value="${_esc(_noteSearchQuery)}" />
      <button class="proj-btn ${_noteFilter === 'all' ? 'primary' : ''}" data-filter="all">All (${_projectNotes.length})</button>
      <button class="proj-btn ${_noteFilter === 'pinned' ? 'primary' : ''}" data-filter="pinned"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg> Pinned (${_projectNotes.filter((n) => n.pinned).length})</button>
      <button class="proj-btn ${_noteFilter === 'checklist' ? 'primary' : ''}" data-filter="checklist"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg> Checklists</button>
      <button class="proj-btn ${_noteFilter === 'note' ? 'primary' : ''}" data-filter="note"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> Notes</button>
      <button class="proj-btn ${_noteFilter === 'files' ? 'primary' : ''}" data-filter="files"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg> Files</button>
    </div>

    <!-- Notes Masonry Grid -->
    ${visibleNotes.length === 0 ? `
      <div style="color:var(--fg-muted,#888); text-align:center; padding:40px; background:var(--bg-elev,#222); border-radius:8px; border:1px solid var(--border,#333);">
        No notes or checklists match this filter. Create your first note or checklist above!
      </div>
    ` : ''}

    ${pinnedNotes.length > 0 ? `
      <div class="proj-section-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg> Pinned</div>
      <div class="proj-notes-grid">
        ${pinnedNotes.map((n) => _renderNoteCardHtml(n)).join('')}
      </div>
    ` : ''}

    ${otherNotes.length > 0 ? `
      ${pinnedNotes.length > 0 ? '<div class="proj-section-title">Others</div>' : ''}
      <div class="proj-notes-grid">
        ${otherNotes.map((n) => _renderNoteCardHtml(n)).join('')}
      </div>
    ` : ''}
  `;

  // Wire Manifest Task Checkboxes (synced with PROJECT.md)
  container.querySelectorAll('.proj-manifest-task-checkbox').forEach(cb => {
    cb.addEventListener('change', async () => {
      const taskId = cb.getAttribute('data-task-id');
      const isChecked = cb.checked;
      try {
        const res = await fetch(`/api/projects/${p.id}/tasks/${taskId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ completed: isChecked }),
        });
        if (!res.ok) throw new Error('Task update failed');
        const task = (p.tasks || []).find(t => t.id === taskId);
        if (task) task.completed = isChecked;
        p.task_completed = (p.tasks || []).filter(t => t.completed).length;
        p.progress = (p.task_total > 0) ? Math.round((p.task_completed / p.task_total) * 100) : 0;
        _updateHeaderState();
        _renderTasksTab(container);
        uiModule.showToast(isChecked ? 'Task marked complete!' : 'Task reopened');
      } catch (err) {
        uiModule.showError('Task update error: ' + err.message);
        cb.checked = !isChecked;
      }
    });
  });

  // Wire Manifest Task Delete
  container.querySelectorAll('.proj-manifest-del-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const taskId = btn.getAttribute('data-task-id');
      try {
        const res = await fetch(`/api/projects/${p.id}/tasks/${taskId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Task delete failed');
        p.tasks = (p.tasks || []).filter(t => t.id !== taskId);
        p.task_total = p.tasks.length;
        p.task_completed = p.tasks.filter(t => t.completed).length;
        p.progress = (p.task_total > 0) ? Math.round((p.task_completed / p.task_total) * 100) : 0;
        _updateHeaderState();
        _renderTasksTab(container);
        uiModule.showToast('Task deleted from PROJECT.md');
      } catch (err) {
        uiModule.showError('Delete error: ' + err.message);
      }
    });
  });

  // Wire Manifest Task Add
  const handleAddManifestTask = async () => {
    const input = container.querySelector('#proj-manifest-new-input');
    const title = input?.value.trim();
    if (!title) return;
    try {
      const res = await fetch(`/api/projects/${p.id}/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      });
      if (!res.ok) throw new Error('Task creation failed');
      const data = await res.json();
      if (!p.tasks) p.tasks = [];
      p.tasks.push(data.task);
      p.task_total = p.tasks.length;
      p.task_completed = p.tasks.filter(t => t.completed).length;
      p.progress = (p.task_total > 0) ? Math.round((p.task_completed / p.task_total) * 100) : 0;
      _updateHeaderState();
      _renderTasksTab(container);
      uiModule.showToast('Task added to PROJECT.md');
    } catch (err) {
      uiModule.showError('Add task error: ' + err.message);
    }
  };

  container.querySelector('#proj-manifest-new-btn')?.addEventListener('click', handleAddManifestTask);
  container.querySelector('#proj-manifest-new-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddManifestTask();
    }
  });

  // Wire compact composer click
  const compactEl = container.querySelector('#proj-composer-compact');
  if (compactEl) {
    compactEl.addEventListener('click', (e) => {
      const modeBtn = e.target.closest('[data-mode]');
      if (modeBtn) {
        _composerType = modeBtn.getAttribute('data-mode');
      }
      _composerExpanded = true;
      _renderTasksTab(container);
      setTimeout(() => {
        const titleInput = container.querySelector('#proj-comp-title-input');
        titleInput?.focus();
      }, 30);
    });
  }

  // Wire close composer button
  container.querySelector('#proj-comp-close-btn')?.addEventListener('click', () => {
    _composerExpanded = false;
    _renderTasksTab(container);
  });

  // Wire composer mode switches
  container.querySelectorAll('.proj-type-pill').forEach((pill) => {
    pill.addEventListener('click', () => {
      _saveComposerState(container);
      _composerType = pill.getAttribute('data-type');
      _renderTasksTab(container);
    });
  });

  // Wire composer color selection
  container.querySelectorAll('.proj-color-dot').forEach((dot) => {
    dot.addEventListener('click', () => {
      _saveComposerState(container);
      _composerColor = dot.getAttribute('data-color');
      _renderTasksTab(container);
    });
  });

  // Wire composer pin toggle
  container.querySelector('#proj-comp-pin-btn')?.addEventListener('click', () => {
    _composerPinned = !_composerPinned;
    _renderTasksTab(container);
  });

  // Wire checklist row Enter key
  container.querySelectorAll('.proj-comp-row-input').forEach((input) => {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const idx = parseInt(input.getAttribute('data-idx'));
        _composerChecklistRows[idx] = input.value;
        _composerChecklistRows.splice(idx + 1, 0, '');
        _renderTasksTab(container);
        setTimeout(() => {
          const nextInput = container.querySelector(`.proj-comp-row-input[data-idx="${idx + 1}"]`);
          nextInput?.focus();
        }, 30);
      }
    });
    input.addEventListener('input', () => {
      const idx = parseInt(input.getAttribute('data-idx'));
      _composerChecklistRows[idx] = input.value;
    });
  });

  // Wire file attachments dropzone
  const dropzone = container.querySelector('#proj-comp-dropzone');
  const fileInput = container.querySelector('#proj-comp-file-input');
  if (dropzone && fileInput) {
    dropzone.addEventListener('click', () => fileInput.click());
    dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
    dropzone.addEventListener('drop', async (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files?.length) {
        for (const file of e.dataTransfer.files) {
          try {
            _notifyToast(`Uploading ${file.name}...`);
            const att = await _uploadAndAttachFile(file);
            _composerAttachments.push(att);
          } catch (err) {
            _notifyToast(err.message, true);
          }
        }
        _renderTasksTab(container);
      }
    });
    fileInput.addEventListener('change', async () => {
      if (fileInput.files?.length) {
        for (const file of fileInput.files) {
          try {
            _notifyToast(`Uploading ${file.name}...`);
            const att = await _uploadAndAttachFile(file);
            _composerAttachments.push(att);
          } catch (err) {
            _notifyToast(err.message, true);
          }
        }
        _renderTasksTab(container);
      }
    });
  }

  // Wire extra file attachment button
  const extraFileInput = container.querySelector('#proj-comp-extra-file');
  extraFileInput?.addEventListener('change', async () => {
    if (extraFileInput.files?.length) {
      for (const file of extraFileInput.files) {
        try {
          _notifyToast(`Uploading ${file.name}...`);
          const att = await _uploadAndAttachFile(file);
          _composerAttachments.push(att);
        } catch (err) {
          _notifyToast(err.message, true);
        }
      }
      _renderTasksTab(container);
    }
  });

  // Remove attachment chip
  container.querySelectorAll('.remove-att').forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.getAttribute('data-idx'));
      _composerAttachments.splice(idx, 1);
      _renderTasksTab(container);
    });
  });

  // Save button
  container.querySelector('#proj-comp-save-btn')?.addEventListener('click', async () => {
    const title = container.querySelector('#proj-comp-title-input')?.value.trim() || '';
    let content = container.querySelector('#proj-comp-content-input')?.value.trim() || null;
    let items = null;

    if (_composerType === 'todo') {
      const rows = _composerChecklistRows.map((r) => r.trim()).filter(Boolean);
      if (rows.length > 0) {
        items = rows.map((r) => ({ text: r, done: false }));
      }
    }

    if (!title && !content && (!items || items.length === 0) && _composerAttachments.length === 0) {
      _notifyToast('Please provide a title, content, or checklist items.', true);
      return;
    }

    const payload = {
      project_id: p.id,
      title: title || (_composerType === 'todo' ? 'Checklist' : 'Note'),
      content: content,
      items: items,
      note_type: _composerType === 'todo' ? 'checklist' : 'note',
      color: _composerColor,
      pinned: _composerPinned,
      attachments: _composerAttachments,
    };

    try {
      _notifyToast('Saving note...');
      const res = await fetch('/api/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error('Failed to save note');
      
      // Reset composer
      _composerChecklistRows = [''];
      _composerAttachments = [];
      _composerPinned = false;
      _composerColor = 'default';

      await _loadProjectDetail(p.id, true);
    } catch (err) {
      _notifyToast('Save note error: ' + err.message, true);
    }
  });

  // Search filter
  const searchInput = container.querySelector('#proj-note-search');
  searchInput?.addEventListener('input', () => {
    _saveComposerState(container);
    _noteSearchQuery = searchInput.value;
    _renderTasksTab(container);
    const newSearch = container.querySelector('#proj-note-search');
    if (newSearch) {
      newSearch.focus();
      newSearch.setSelectionRange(_noteSearchQuery.length, _noteSearchQuery.length);
    }
  });

  // Filter buttons
  container.querySelectorAll('.proj-filter-bar button[data-filter]').forEach((btn) => {
    btn.addEventListener('click', () => {
      _saveComposerState(container);
      _noteFilter = btn.getAttribute('data-filter');
      _renderTasksTab(container);
    });
  });

  // Wire cards events
  _wireNoteCards(container, p);
}

function _renderNoteCardHtml(note) {
  const colorClass = (note.color && note.color !== 'default') ? `color-${note.color}` : '';
  
  let items = [];
  if (Array.isArray(note.items)) items = note.items;
  else if (typeof note.items === 'string') {
    try { items = JSON.parse(note.items); } catch {}
  }
  const isChecklist = note.note_type === 'checklist' || (Array.isArray(items) && items.length > 0);
  const completedCount = items.filter((it) => it.done || it.checked).length;
  const totalCount = items.length;

  let attachments = [];
  if (Array.isArray(note.attachments)) attachments = note.attachments;
  else if (typeof note.attachments === 'string') {
    try { attachments = JSON.parse(note.attachments); } catch {}
  }

  return `
    <div class="proj-note-card ${colorClass}" data-id="${_esc(note.id)}">
      <div class="proj-note-header">
        <div class="proj-note-title" data-id="${_esc(note.id)}">${_esc(note.title || 'Untitled Note')}</div>
        <div class="proj-note-toolbar">
          <button type="button" class="proj-card-btn pin-btn ${note.pinned ? 'active' : ''}" data-id="${_esc(note.id)}" title="${note.pinned ? 'Unpin' : 'Pin to top'}">📌</button>
          <label class="proj-card-btn" title="Attach file" style="cursor:pointer;">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
            <input type="file" class="proj-card-attach-input" data-id="${_esc(note.id)}" multiple style="display:none;" />
          </label>
          <button type="button" class="proj-card-btn agent-btn proj-card-agent-btn" data-id="${_esc(note.id)}" title="Solve with Agent"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg></button>
          <button type="button" class="proj-card-btn del-btn proj-card-del-btn" data-id="${_esc(note.id)}" title="Delete Note"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>
        </div>
      </div>

      ${isChecklist ? `
        <div class="proj-note-checklist">
          ${items.map((it, idx) => `
            <div class="proj-note-check-item ${(it.done || it.checked) ? 'done' : ''}" data-idx="${idx}">
              <button type="button" class="proj-check-dot proj-card-check-dot" data-note-id="${_esc(note.id)}" data-idx="${idx}" title="Toggle completed"></button>
              <span class="proj-check-text" data-note-id="${_esc(note.id)}" data-idx="${idx}" tabindex="0">${_esc(it.text || '')}</span>
              <button type="button" class="proj-card-btn del-btn proj-del-item-btn" data-note-id="${_esc(note.id)}" data-idx="${idx}" title="Remove item" style="padding:0 3px; font-size:10px; opacity:0.5;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
            </div>
          `).join('')}
          <div style="display:flex; align-items:center; gap:6px; margin-top:4px;">
            <input type="text" class="proj-comp-row-input proj-card-add-item-input" data-note-id="${_esc(note.id)}" placeholder="+ Add item (Press Enter)..." />
          </div>
          ${totalCount > 0 ? `
            <div style="font-size:11px; color:var(--fg-muted,#888); margin-top:2px;">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg> ${completedCount}/${totalCount} completed
            </div>
          ` : ''}
        </div>
      ` : ''}

      ${(!isChecklist && note.content) ? `
        <div class="proj-note-body-text">${_esc(note.content)}</div>
      ` : ''}

      <!-- Attachments Gallery -->
      ${attachments.length > 0 ? `
        <div class="proj-card-attachments">
          ${attachments.map((att) => {
            const isImg = _isImageMime(att.mime_type, att.filename);
            const isPdf = _isPdfMime(att.mime_type, att.filename);
            if (isImg) {
              return `
                <img src="${_esc(att.url)}" class="proj-att-img-preview" data-url="${_esc(att.url)}" data-title="${_esc(att.filename)}" alt="${_esc(att.filename)}" title="Click to view image" />
              `;
            }
            return `
              <div class="proj-att-file-chip" data-url="${_esc(att.url)}" data-title="${_esc(att.filename)}" data-mime="${_esc(att.mime_type || '')}" title="Click to view document">
                <div class="proj-att-file-info">
                  <span>${isPdf ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 15h6"/><path d="M9 11h6"/></svg>' : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>'}</span>
                  <span class="proj-att-file-name">${_esc(att.filename)}</span>
                </div>
                <span style="color:var(--fg-muted,#888); font-size:10px;">${_formatBytes(att.size)}</span>
              </div>
            `;
          }).join('')}
        </div>
      ` : ''}
    </div>
  `;
}

function _wireNoteCards(container, project) {
  // Check-dot toggles
  container.querySelectorAll('.proj-card-check-dot').forEach((dot) => {
    dot.addEventListener('click', async (e) => {
      e.stopPropagation();
      const noteId = dot.getAttribute('data-note-id');
      const idx = parseInt(dot.getAttribute('data-idx'));
      const note = _projectNotes.find((n) => n.id === noteId);
      if (!note || !Array.isArray(note.items) || !note.items[idx]) return;

      const wasDone = note.items[idx].done || note.items[idx].checked;
      note.items[idx].done = !wasDone;
      _renderTasksTab(container);

      // Check confetti on full card completion
      if (!wasDone && note.items.every((it) => it.done || it.checked)) {
        const r = dot.getBoundingClientRect();
        if (typeof spawnConfetti === 'function') {
          spawnConfetti(r.left + r.width / 2, r.top + r.height / 2, 60);
        }
      }

      try {
        await fetch(`/api/notes/${noteId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ items: note.items }),
        });
      } catch (err) {
        _notifyToast('Failed to update task: ' + err.message, true);
      }
    });
  });

  
  // Inline edit checklist text
  container.querySelectorAll('.proj-check-text').forEach((el) => {
    el.addEventListener('dblclick', (e) => {
      e.stopPropagation();
      el.setAttribute('contenteditable', 'true');
      el.focus();
      
      // Select all text on edit
      const range = document.createRange();
      range.selectNodeContents(el);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    });

    el.addEventListener('blur', async (e) => {
      if (el.getAttribute('contenteditable') !== 'true') return;
      el.removeAttribute('contenteditable');
      const noteId = el.getAttribute('data-note-id');
      const idx = parseInt(el.getAttribute('data-idx'));
      const text = el.innerText.trim();
      const note = _projectNotes.find((n) => n.id === noteId);
      if (note && Array.isArray(note.items) && note.items[idx]) {
        if (note.items[idx].text !== text) {
          note.items[idx].text = text;
          try {
            await fetch(`/api/notes/${noteId}`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ items: note.items }),
            });
          } catch (err) {
            _notifyToast(err.message, true);
          }
        }
      }
    });

    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        el.blur();
      }
    });
  });


  // Add checklist item inline on card
  container.querySelectorAll('.proj-card-add-item-input').forEach((input) => {
    input.addEventListener('keydown', async (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;
        const noteId = input.getAttribute('data-note-id');
        const note = _projectNotes.find((n) => n.id === noteId);
        if (!note) return;

        if (!Array.isArray(note.items)) note.items = [];
        note.items.push({ text: text, done: false });
        input.value = '';
        _renderTasksTab(container);

        try {
          await fetch(`/api/notes/${noteId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: note.items }),
          });
        } catch (err) {
          _notifyToast(err.message, true);
        }
      }
    });
  });

  // Delete checklist item on card
  container.querySelectorAll('.proj-del-item-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const noteId = btn.getAttribute('data-note-id');
      const idx = parseInt(btn.getAttribute('data-idx'));
      const note = _projectNotes.find((n) => n.id === noteId);
      if (!note || !Array.isArray(note.items)) return;

      note.items.splice(idx, 1);
      _renderTasksTab(container);

      try {
        await fetch(`/api/notes/${noteId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ items: note.items }),
        });
      } catch (err) {
        _notifyToast(err.message, true);
      }
    });
  });

  // Lightbox Image Viewer trigger
  container.querySelectorAll('.proj-att-img-preview').forEach((img) => {
    img.addEventListener('click', (e) => {
      e.stopPropagation();
      const url = img.getAttribute('data-url');
      const title = img.getAttribute('data-title') || 'Image Preview';
      _openImageLightbox(url, title);
    });
  });

  // Document Viewer trigger
  container.querySelectorAll('.proj-att-file-chip').forEach((chip) => {
    chip.addEventListener('click', (e) => {
      e.stopPropagation();
      const url = chip.getAttribute('data-url');
      const title = chip.getAttribute('data-title') || 'Document';
      const mime = chip.getAttribute('data-mime') || '';
      _openDocumentViewer(url, title, mime);
    });
  });

  // Card file attachment input
  container.querySelectorAll('.proj-card-attach-input').forEach((input) => {
    input.addEventListener('change', async (e) => {
      e.stopPropagation();
      const noteId = input.getAttribute('data-id');
      const note = _projectNotes.find((n) => n.id === noteId);
      if (!note || !input.files?.length) return;

      if (!Array.isArray(note.attachments)) note.attachments = [];
      for (const file of input.files) {
        try {
          _notifyToast(`Uploading ${file.name}...`);
          const att = await _uploadAndAttachFile(file);
          note.attachments.push(att);
        } catch (err) {
          _notifyToast(err.message, true);
        }
      }
      _renderTasksTab(container);

      try {
        await fetch(`/api/notes/${noteId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ attachments: note.attachments }),
        });
      } catch (err) {
        _notifyToast(err.message, true);
      }
    });
  });

  // Pin toggle
  container.querySelectorAll('.pin-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const noteId = btn.getAttribute('data-id');
      const note = _projectNotes.find((n) => n.id === noteId);
      if (!note) return;

      note.pinned = !note.pinned;
      _renderTasksTab(container);

      try {
        await fetch(`/api/notes/${noteId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pinned: note.pinned }),
        });
      } catch (err) {
        _notifyToast(err.message, true);
      }
    });
  });

  // Solve with Agent button
  container.querySelectorAll('.proj-card-agent-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const noteId = btn.getAttribute('data-id');
      const note = _projectNotes.find((n) => n.id === noteId);
      if (!note) return;

      try {
        _notifyToast(`Spawning Agent session for: "${note.title}"...`);
        const res = await fetch(`/api/projects/${project.id}/agent_session`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_id: note.id, task_title: note.title }),
        });
        if (!res.ok) throw new Error('Failed to spawn agent session');
        const data = await res.json();
        closeProjects();
        if (window.sessionModule?.switchSession) {
          window.sessionModule.switchSession(data.session_id);
        }
      } catch (err) {
        _notifyToast('Agent launch error: ' + err.message, true);
      }
    });
  });

  // Delete note card
  container.querySelectorAll('.proj-card-del-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm('Are you sure you want to delete this note?')) return;
      const noteId = btn.getAttribute('data-id');
      const idx = _projectNotes.findIndex((n) => n.id === noteId);
      if (idx >= 0) {
        _projectNotes.splice(idx, 1);
        _renderTasksTab(container);
      }

      try {
        await fetch(`/api/notes/${noteId}`, { method: 'DELETE' });
        await _loadProjectDetail(project.id, true);
      } catch (err) {
        _notifyToast(err.message, true);
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Tab 3: Documents & Files
// ---------------------------------------------------------------------------

function _renderDocsTab(container) {
  const p = _currentProject;
  const docs = p.docs || [];

  container.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
      <h3 style="margin:0;">Project Directory & Documents</h3>
      <div style="font-size:12px; color:var(--fg-muted,#888);">Path: <code>${_esc(p.folder_path)}</code></div>
    </div>

    <div class="proj-docs-grid">
      <div class="proj-doc-card" id="proj-open-manifest-card">
        <div style="margin-bottom:6px;"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="opacity:0.7;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg></div>
        <div style="font-weight:600; font-size:13px; margin-bottom:4px;">PROJECT.md</div>
        <div style="font-size:11px; color:var(--fg-muted,#888);">Living Spec & Manifest</div>
      </div>
      <div class="proj-doc-card">
        <div style="margin-bottom:6px;"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="opacity:0.7;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></div>
        <div style="font-weight:600; font-size:13px; margin-bottom:4px;">docs/</div>
        <div style="font-size:11px; color:var(--fg-muted,#888);">Reference Documentation</div>
      </div>
      <div class="proj-doc-card">
        <div style="margin-bottom:6px;"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="opacity:0.7;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></div>
        <div style="font-weight:600; font-size:13px; margin-bottom:4px;">tasks/</div>
        <div style="font-size:11px; color:var(--fg-muted,#888);">Detailed Task Specs</div>
      </div>
      <div class="proj-doc-card">
        <div style="margin-bottom:6px;"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="opacity:0.7;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></div>
        <div style="font-weight:600; font-size:13px; margin-bottom:4px;">logs/</div>
        <div style="font-size:11px; color:var(--fg-muted,#888);">Agent Execution Runs</div>
      </div>
    </div>
  `;

  container.querySelector('#proj-open-manifest-card')?.addEventListener('click', () => {
    _activeTab = 'overview';
    _isEditingSummary = false;
    document.querySelectorAll('.proj-tab').forEach((b) => b.classList.toggle('active', b.getAttribute('data-tab') === 'overview'));
    _renderActiveTabContent();
  });
}

// ---------------------------------------------------------------------------
// Tab 4: Linked Work
// ---------------------------------------------------------------------------

function _renderLinksTab(container) {
  const p = _currentProject;
  const links = p.links || [];

  container.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
      <h3 style="margin:0;">Cross-Module Linked Entities</h3>
      <button id="proj-add-link-btn" class="proj-btn primary">+ Link Entity</button>
    </div>

    ${links.length === 0 ? '<div style="color:var(--fg-muted,#888); text-align:center; padding:30px;">No external entities linked yet. Link operations items, email threads, calendar events, or documents.</div>' : ''}

    <div class="proj-links-grid">
      ${links.map((l) => `
        <div class="proj-link-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span class="proj-link-type-badge">${_esc(l.target_type)}</span>
            <button class="proj-btn proj-del-link-btn" data-id="${_esc(l.id)}" title="Unlink" style="padding:2px 6px;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
          </div>
          <div style="font-weight:600; font-size:13px;">${_esc(l.label)}</div>
          <div class="proj-link-target">${_esc(l.target_id)}</div>
        </div>
      `).join('')}
    </div>
  `;

  container.querySelectorAll('.proj-del-link-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const linkId = btn.getAttribute('data-id');
      try {
        await fetch(`/api/projects/${p.id}/links/${linkId}`, { method: 'DELETE' });
        await _loadProjectDetail(p.id);
      } catch (err) {
        _notifyToast(err.message, true);
      }
    });
  });

  container.querySelector('#proj-add-link-btn')?.addEventListener('click', () => {
    _renderAddLinkInlineForm();
  });
}

// ---------------------------------------------------------------------------
// Forms & Helpers
// ---------------------------------------------------------------------------

function _renderEmptyState() {
  const body = document.getElementById('proj-body');
  if (!body) return;
  body.innerHTML = `
    <div style="text-align:center; padding: 60px 20px; color:var(--fg-muted,#888);">
      <h3 style="margin-bottom:8px;">No projects yet.</h3>
      <p style="margin-bottom:18px; font-size:13px;">Create a structured project workspace for tasks, documents, notes, and links.</p>
      <button id="proj-empty-new-btn" class="proj-btn primary" style="padding:8px 16px; font-size:13px;">+ New Project</button>
    </div>
  `;
  body.querySelector('#proj-empty-new-btn')?.addEventListener('click', _renderNewProjectInlineForm);
}

function _renderNewProjectInlineForm() {
  const body = document.getElementById('proj-body');
  if (!body) return;

  body.innerHTML = `
    <div class="proj-inline-form">
      <h3 style="margin-top:0;">Create New Project</h3>
      <label for="proj-create-name-input">Project Name</label>
      <input type="text" id="proj-create-name-input" class="proj-inline-input" placeholder="e.g. Website Redesign" autocomplete="off" />
      <label for="proj-create-desc-input" style="margin-top:10px;">Description</label>
      <input type="text" id="proj-create-desc-input" class="proj-inline-input" placeholder="e.g. Redesign and optimize landing pages" autocomplete="off" />
      <div class="proj-inline-form-actions">
        <button id="proj-create-cancel-btn" class="proj-btn">Cancel</button>
        <button id="proj-create-submit-btn" class="proj-btn primary">Create Project</button>
      </div>
    </div>
  `;

  const inputName = body.querySelector('#proj-create-name-input');
  inputName?.focus();

  body.querySelector('#proj-create-cancel-btn')?.addEventListener('click', () => {
    if (_currentProjectId) _loadProjectDetail(_currentProjectId);
    else _renderEmptyState();
  });

  body.querySelector('#proj-create-submit-btn')?.addEventListener('click', async () => {
    const name = inputName?.value.trim();
    const desc = body.querySelector('#proj-create-desc-input')?.value.trim();
    if (!name) {
      uiModule.showError('Project name cannot be empty.');
      return;
    }

    try {
      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description: desc }),
      });
      if (!res.ok) throw new Error('Creation failed');
      const data = await res.json();
      _currentProjectId = data.project.id;
      uiModule.showToast(`Project "${name}" created!`);
      await _fetchProjectsList();
      await _loadProjectDetail(_currentProjectId);
    } catch (err) {
      uiModule.showError('Error creating project: ' + err.message);
    }
  });
}

function _renderAddLinkInlineForm() {
  const body = document.getElementById('proj-body');
  const p = _currentProject;
  if (!body || !p) return;

  body.innerHTML = `
    <div class="proj-inline-form">
      <h3 style="margin-top:0;">Link External Entity</h3>
      <label for="proj-link-type-select">Target Type</label>
      <select id="proj-link-type-select" class="proj-inline-input">
        <option value="operations">Operations (Bil Weekend)</option>
        <option value="email">Email Thread / Message</option>
        <option value="calendar">Calendar Event</option>
        <option value="document">Document / Spec</option>
      </select>
      <label for="proj-link-target-input" style="margin-top:10px;">Target Identifier / Key</label>
      <input type="text" id="proj-link-target-input" class="proj-inline-input" placeholder="e.g. bookings:1042 or doc_id" autocomplete="off" />
      <label for="proj-link-label-input" style="margin-top:10px;">Label (Optional)</label>
      <input type="text" id="proj-link-label-input" class="proj-inline-input" placeholder="e.g. Client Booking Review" autocomplete="off" />
      <div class="proj-inline-form-actions">
        <button id="proj-link-cancel-btn" class="proj-btn">Cancel</button>
        <button id="proj-link-submit-btn" class="proj-btn primary">Add Link</button>
      </div>
    </div>
  `;

  body.querySelector('#proj-link-cancel-btn')?.addEventListener('click', () => {
    _renderLinksTab(body);
  });

  body.querySelector('#proj-link-submit-btn')?.addEventListener('click', async () => {
    const targetType = body.querySelector('#proj-link-type-select')?.value;
    const targetId = body.querySelector('#proj-link-target-input')?.value.trim();
    const label = body.querySelector('#proj-link-label-input')?.value.trim() || targetId;

    if (!targetId) {
      uiModule.showError('Target identifier is required.');
      return;
    }

    try {
      const res = await fetch(`/api/projects/${p.id}/links`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_type: targetType, target_id: targetId, label }),
      });
      if (!res.ok) throw new Error('Failed to create link');
      _notifyToast('Entity linked to project!');
      await _loadProjectDetail(p.id);
    } catch (err) {
      _notifyToast('Link creation error: ' + err.message, true);
    }
  });
}

function _loggerError(err) {
  _loggerError('[Projects]', err);
}

// ---------------------------------------------------------------------------
// Public Exports
// ---------------------------------------------------------------------------

export function openProjects(projectId = null) {
  if (projectId) _currentProjectId = projectId;
  else _currentProjectId = null; // Force landing page on open
  
  _injectStyles();
  _modal = _renderModalSkeleton();
  _open = true;
  _modal.classList.remove('hidden');
  _modal.style.display = 'flex';
  document.getElementById('tool-projects-btn')?.classList.add('active');
  
  _fetchProjectsList().then(() => {
    _updateActionButtonsEnabled();
    if (_currentProjectId) {
      _loadProjectDetail(_currentProjectId);
    } else {
      _loadProjectDetail(null);
    }
  });
}

export function closeProjects() {
  _open = false;
  if (_modal) {
    _modal.classList.add('hidden');
    _modal.style.display = 'none';
  }
  document.getElementById('tool-projects-btn')?.classList.remove('active');
}

export function isProjectsOpen() {
  return _open;
}

export default {
  openProjects,
  closeProjects,
  isProjectsOpen,
};

if (typeof window !== 'undefined') {
  window.projectsModule = { openProjects, closeProjects, isProjectsOpen };
}
