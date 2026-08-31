// static/js/projects.js
/**
 * Projects Module — Hybrid Project Workspace Hub for Odysseus.
 * Combines File-as-Spec (PROJECT.md) with SQLite indexing, interactive task lists,
 * document browsing, and cross-module link management (Operations, Email, Calendar, Docs).
 */

import { makeWindowDraggable } from './windowDrag.js';
import uiModule from './ui.js';
import markdownModule from './markdown.js';

let _open = false;
let _modal = null;
let _projects = [];
let _currentProjectId = null;
let _currentProject = null;
let _activeTab = 'overview'; // 'overview' | 'tasks' | 'docs' | 'links'
let _taskFilter = 'all'; // 'all' | 'active' | 'completed'
let _isEditingSummary = false;
let _stylesInjected = false;

function _esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function _injectStyles() {
  if (_stylesInjected) return;
  _stylesInjected = true;
  const style = document.createElement('style');
  style.id = 'projects-styles';
  style.textContent = `
    #projects-modal .proj-modal-content {
      width: min(1000px, 94vw);
      height: min(720px, 88vh);
      display: flex;
      flex-direction: column;
      background: var(--bg, #1a1a1a);
      color: var(--fg, #eee);
      border: 1px solid var(--border, #333);
      border-radius: 10px;
      box-shadow: 0 12px 36px rgba(0,0,0,0.45);
      overflow: hidden;
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
    .proj-pill.paused { background: rgba(241, 196, 15, 0.18); color: #f1c40f; border: 1px solid #f1c40f; }
    .proj-pill.completed { background: rgba(52, 152, 219, 0.18); color: #3498db; border: 1px solid #3498db; }
    
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
    .proj-markdown-content { background: var(--bg-elev, #202020); border: 1px solid var(--border, #333); border-radius: 8px; padding: 16px; line-height: 1.6; }
    .proj-summary-editor { width: 100%; height: 340px; background: var(--input-bg, #181818); color: var(--fg, #eee); border: 1px solid var(--border, #444); border-radius: 8px; padding: 12px; font-family: monospace; font-size: 12px; resize: vertical; }

    /* Tab: Tasks */
    .proj-task-filter-bar { display: flex; gap: 8px; margin-bottom: 14px; align-items: center; }
    .proj-task-list { display: flex; flex-direction: column; gap: 8px; }
    .proj-task-item { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: var(--bg-elev, #222); border: 1px solid var(--border, #333); border-radius: 6px; }
    .proj-task-item.completed span { text-decoration: line-through; color: var(--fg-muted, #777); }
    .proj-task-checkbox { cursor: pointer; width: 16px; height: 16px; }
    .proj-task-input-bar { display: flex; gap: 8px; margin-bottom: 16px; }
    .proj-task-input { flex: 1; background: var(--input-bg, #1e1e1e); border: 1px solid var(--border, #444); border-radius: 6px; padding: 8px 12px; color: var(--fg, #eee); font-size: 13px; }

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
    <div class="modal-backdrop"></div>
    <div class="proj-modal-content">
      <div class="proj-header">
        <select id="proj-select" class="proj-select" aria-label="Select Project"></select>
        <span id="proj-status-badge" class="proj-pill active">ACTIVE</span>
        <button id="proj-new-btn" class="proj-btn primary" title="Create Project">+ New Project</button>
        <button id="proj-sync-btn" class="proj-btn" title="Sync with disk PROJECT.md">🔄 Sync Disk</button>
        <button id="proj-agent-btn" class="proj-btn" title="Spawn Agent Session">🤖 Agent Session</button>
        <div style="margin-left:auto; display:flex; gap:6px;">
          <button id="proj-close-btn" class="proj-btn" title="Close">✕</button>
        </div>
      </div>
      <div class="proj-tabs">
        <button class="proj-tab ${(_activeTab === 'overview') ? 'active' : ''}" data-tab="overview">
          📋 Overview & Summary
        </button>
        <button class="proj-tab ${(_activeTab === 'tasks') ? 'active' : ''}" data-tab="tasks">
          ✓ To-Dos <span id="proj-tasks-badge" class="proj-tab-badge">0/0</span>
        </button>
        <button class="proj-tab ${(_activeTab === 'docs') ? 'active' : ''}" data-tab="docs">
          📁 Documents & Files
        </button>
        <button class="proj-tab ${(_activeTab === 'links') ? 'active' : ''}" data-tab="links">
          🔗 Linked Work <span id="proj-links-badge" class="proj-tab-badge">0</span>
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
  modalEl.querySelector('.modal-backdrop')?.addEventListener('click', closeProjects);
  modalEl.querySelector('#proj-close-btn')?.addEventListener('click', closeProjects);
  
  modalEl.querySelector('#proj-select')?.addEventListener('change', async (e) => {
    _currentProjectId = e.target.value;
    await _loadProjectDetail(_currentProjectId);
  });

  modalEl.querySelector('#proj-sync-btn')?.addEventListener('click', async () => {
    if (!_currentProjectId) return;
    try {
      const res = await fetch(`/api/projects/${_currentProjectId}/sync`, { method: 'POST' });
      if (!res.ok) throw new Error('Sync failed');
      uiModule.showToast('Project synced with disk!');
      await _loadProjectDetail(_currentProjectId);
    } catch (err) {
      uiModule.showError('Disk sync error: ' + err.message);
    }
  });

  modalEl.querySelector('#proj-agent-btn')?.addEventListener('click', async () => {
    if (!_currentProjectId) return;
    try {
      const res = await fetch(`/api/projects/${_currentProjectId}/agent_session`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed to spawn session');
      const data = await res.json();
      uiModule.showToast('Agent session launched for project!');
      closeProjects();
      if (window.sessionModule?.switchSession) {
        window.sessionModule.switchSession(data.session_id);
      }
    } catch (err) {
      uiModule.showError('Session launch error: ' + err.message);
    }
  });

  modalEl.querySelector('#proj-new-btn')?.addEventListener('click', () => {
    _renderNewProjectPrompt();
  });

  modalEl.querySelectorAll('.proj-tab').forEach((tabBtn) => {
    tabBtn.addEventListener('click', () => {
      _activeTab = tabBtn.getAttribute('data-tab');
      modalEl.querySelectorAll('.proj-tab').forEach((b) => b.classList.toggle('active', b === tabBtn));
      _renderActiveTabContent();
    });
  });

  makeWindowDraggable(modalEl.querySelector('.proj-modal-content'), modalEl.querySelector('.proj-header'));
}

// ---------------------------------------------------------------------------
// Data Fetching & State
// ---------------------------------------------------------------------------

async function _fetchProjectsList() {
  try {
    const res = await fetch('/api/projects');
    if (!res.ok) throw new Error('Failed to fetch projects list');
    const data = await res.json();
    _projects = data.projects || [];
    
    const selectEl = document.getElementById('proj-select');
    if (selectEl) {
      selectEl.innerHTML = _projects.map((p) => `
        <option value="${_esc(p.id)}" ${p.id === _currentProjectId ? 'selected' : ''}>
          ${_esc(p.name)}
        </option>
      `).join('');
    }

    if (!_currentProjectId && _projects.length > 0) {
      _currentProjectId = _projects[0].id;
    }
  } catch (err) {
    loggerError(err);
  }
}

async function _loadProjectDetail(projectId) {
  if (!projectId) return;
  const bodyEl = document.getElementById('proj-body');
  if (bodyEl) {
    bodyEl.innerHTML = `<div style="color:var(--fg-muted,#888); text-align:center; padding:40px;">Loading project details...</div>`;
  }

  try {
    const res = await fetch(`/api/projects/${projectId}`);
    if (!res.ok) throw new Error('Project detail fetch failed');
    const data = await res.json();
    _currentProject = data.project;
    
    _updateHeaderState();
    _renderActiveTabContent();
  } catch (err) {
    if (bodyEl) {
      bodyEl.innerHTML = `<div style="color:var(--color-danger,#d33); padding:20px;">Error: ${_esc(err.message)}</div>`;
    }
  }
}

function _updateHeaderState() {
  if (!_currentProject) return;
  const statusBadge = document.getElementById('proj-status-badge');
  if (statusBadge) {
    statusBadge.textContent = (_currentProject.status || 'ACTIVE').toUpperCase();
    statusBadge.className = `proj-pill ${_esc(_currentProject.status || 'active')}`;
  }

  const tasksBadge = document.getElementById('proj-tasks-badge');
  if (tasksBadge) {
    tasksBadge.textContent = `${_currentProject.task_completed || 0}/${_currentProject.task_total || 0}`;
  }

  const linksBadge = document.getElementById('proj-links-badge');
  if (linksBadge) {
    linksBadge.textContent = String((_currentProject.links || []).length);
  }
}

// ---------------------------------------------------------------------------
// Tab Content Rendering
// ---------------------------------------------------------------------------

function _renderActiveTabContent() {
  const bodyEl = document.getElementById('proj-body');
  if (!bodyEl || !_currentProject) return;

  if (_activeTab === 'overview') {
    _renderOverviewTab(bodyEl);
  } else if (_activeTab === 'tasks') {
    _renderTasksTab(bodyEl);
  } else if (_activeTab === 'docs') {
    _renderDocsTab(bodyEl);
  } else if (_activeTab === 'links') {
    _renderLinksTab(bodyEl);
  }
}

function _renderOverviewTab(container) {
  const p = _currentProject;
  const progress = p.progress || 0;

  if (_isEditingSummary) {
    container.innerHTML = `
      <div class="proj-overview-header">
        <h3 style="margin:0;">Edit Project Manifest (PROJECT.md)</h3>
        <div style="display:flex; gap:8px;">
          <button id="proj-summary-save-btn" class="proj-btn primary">Save Changes</button>
          <button id="proj-summary-cancel-btn" class="proj-btn">Cancel</button>
        </div>
      </div>
      <textarea id="proj-summary-textarea" class="proj-summary-editor">${_esc(p.content || '')}</textarea>
    `;

    container.querySelector('#proj-summary-cancel-btn')?.addEventListener('click', () => {
      _isEditingSummary = false;
      _renderOverviewTab(container);
    });

    container.querySelector('#proj-summary-save-btn')?.addEventListener('click', async () => {
      const newContent = container.querySelector('#proj-summary-textarea')?.value;
      try {
        const res = await fetch(`/api/projects/${p.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: newContent }),
        });
        if (!res.ok) throw new Error('Failed to save project');
        uiModule.showToast('Project updated successfully!');
        _isEditingSummary = false;
        await _loadProjectDetail(p.id);
      } catch (err) {
        uiModule.showError('Save error: ' + err.message);
      }
    });
    return;
  }

  const renderedMd = markdownModule?.mdToHtml ? markdownModule.mdToHtml(p.content || '# ' + p.name) : `<pre>${_esc(p.content)}</pre>`;

  container.innerHTML = `
    <div class="proj-overview-header">
      <div>
        <h2 style="margin:0 0 4px 0;">${_esc(p.name)}</h2>
        <div style="font-size:12px; color:var(--fg-muted,#888);">
          Workspace: <code>${_esc(p.folder_path)}</code> | Priority: <b>${_esc(p.priority)}</b>
        </div>
      </div>
      <button id="proj-summary-edit-btn" class="proj-btn">✏️ Edit Manifest</button>
    </div>

    <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
      <span>Task Completion Progress</span>
      <span>${progress}% (${p.task_completed || 0}/${p.task_total || 0})</span>
    </div>
    <div class="proj-progress-bar">
      <div class="proj-progress-fill" style="width: ${progress}%;"></div>
    </div>

    <div class="proj-markdown-content">
      ${renderedMd}
    </div>
  `;

  container.querySelector('#proj-summary-edit-btn')?.addEventListener('click', () => {
    _isEditingSummary = true;
    _renderOverviewTab(container);
  });
}

function _renderTasksTab(container) {
  const p = _currentProject;
  const tasks = (p.tasks || []).filter((t) => {
    if (_taskFilter === 'active') return !t.completed;
    if (_taskFilter === 'completed') return t.completed;
    return true;
  });

  container.innerHTML = `
    <div class="proj-task-input-bar">
      <input id="proj-new-task-input" type="text" class="proj-task-input" placeholder="Add a new task or checklist item..." />
      <button id="proj-add-task-btn" class="proj-btn primary">+ Add Task</button>
    </div>

    <div class="proj-task-filter-bar">
      <span style="font-size:12px; color:var(--fg-muted,#888);">Filter:</span>
      <button class="proj-btn ${(_taskFilter === 'all') ? 'primary' : ''}" data-filter="all">All (${p.task_total || 0})</button>
      <button class="proj-btn ${(_taskFilter === 'active') ? 'primary' : ''}" data-filter="active">Active (${(p.task_total || 0) - (p.task_completed || 0)})</button>
      <button class="proj-btn ${(_taskFilter === 'completed') ? 'primary' : ''}" data-filter="completed">Completed (${p.task_completed || 0})</button>
    </div>

    <div class="proj-task-list">
      ${tasks.length === 0 ? '<div style="color:var(--fg-muted,#888); padding:20px; text-align:center;">No tasks found in this view.</div>' : ''}
      ${tasks.map((t) => `
        <div class="proj-task-item ${t.completed ? 'completed' : ''}" data-id="${_esc(t.id)}">
          <input type="checkbox" class="proj-task-checkbox" ${t.completed ? 'checked' : ''} data-id="${_esc(t.id)}" />
          <span style="flex:1;">${_esc(t.title)}</span>
          ${t.due_date ? `<span style="font-size:11px; color:var(--fg-muted,#888);">📅 ${_esc(t.due_date)}</span>` : ''}
          <button class="proj-btn proj-task-del-btn" data-id="${_esc(t.id)}" title="Delete Task">🗑️</button>
        </div>
      `).join('')}
    </div>
  `;

  const inputEl = container.querySelector('#proj-new-task-input');
  const addBtn = container.querySelector('#proj-add-task-btn');

  const submitNewTask = async () => {
    const val = inputEl?.value.trim();
    if (!val) return;
    try {
      const res = await fetch(`/api/projects/${p.id}/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: val }),
      });
      if (!res.ok) throw new Error('Failed to add task');
      inputEl.value = '';
      await _loadProjectDetail(p.id);
    } catch (err) {
      uiModule.showError(err.message);
    }
  };

  addBtn?.addEventListener('click', submitNewTask);
  inputEl?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') submitNewTask();
  });

  container.querySelectorAll('.proj-task-checkbox').forEach((cb) => {
    cb.addEventListener('change', async (e) => {
      const taskId = e.target.getAttribute('data-id');
      const isDone = e.target.checked;
      try {
        await fetch(`/api/projects/${p.id}/tasks/${taskId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ completed: isDone }),
        });
        await _loadProjectDetail(p.id);
      } catch (err) {
        uiModule.showError(err.message);
      }
    });
  });

  container.querySelectorAll('.proj-task-del-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const taskId = btn.getAttribute('data-id');
      try {
        await fetch(`/api/projects/${p.id}/tasks/${taskId}`, { method: 'DELETE' });
        await _loadProjectDetail(p.id);
      } catch (err) {
        uiModule.showError(err.message);
      }
    });
  });

  container.querySelectorAll('.proj-task-filter-bar button').forEach((fb) => {
    fb.addEventListener('click', () => {
      _taskFilter = fb.getAttribute('data-filter');
      _renderTasksTab(container);
    });
  });
}

function _renderDocsTab(container) {
  const p = _currentProject;
  container.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
      <h3 style="margin:0;">Project Files & Living Documents</h3>
      <span style="font-size:12px; color:var(--fg-muted,#888);">Location: <code>${_esc(p.folder_path)}</code></span>
    </div>

    <div class="proj-docs-grid">
      <div class="proj-doc-card">
        <div style="font-size:24px; margin-bottom:6px;">📄</div>
        <div style="font-weight:600; font-size:13px; margin-bottom:4px;">PROJECT.md</div>
        <div style="font-size:11px; color:var(--fg-muted,#888);">Master Manifest & Spec</div>
      </div>
      <div class="proj-doc-card">
        <div style="font-size:24px; margin-bottom:6px;">📁</div>
        <div style="font-weight:600; font-size:13px; margin-bottom:4px;">docs/</div>
        <div style="font-size:11px; color:var(--fg-muted,#888);">Reference Documentation</div>
      </div>
      <div class="proj-doc-card">
        <div style="font-size:24px; margin-bottom:6px;">📁</div>
        <div style="font-weight:600; font-size:13px; margin-bottom:4px;">tasks/</div>
        <div style="font-size:11px; color:var(--fg-muted,#888);">Detailed Task Specs</div>
      </div>
      <div class="proj-doc-card">
        <div style="font-size:24px; margin-bottom:6px;">📁</div>
        <div style="font-weight:600; font-size:13px; margin-bottom:4px;">logs/</div>
        <div style="font-size:11px; color:var(--fg-muted,#888);">Agent Execution Runs</div>
      </div>
    </div>
  `;
}

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
            <button class="proj-btn proj-del-link-btn" data-id="${_esc(l.id)}" title="Unlink" style="padding:2px 6px;">✕</button>
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
        uiModule.showError(err.message);
      }
    });
  });

  container.querySelector('#proj-add-link-btn')?.addEventListener('click', () => {
    _renderAddLinkPrompt(p.id);
  });
}

function _renderNewProjectPrompt() {
  const name = prompt('Enter New Project Name:');
  if (!name || !name.trim()) return;

  fetch('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name.trim() }),
  })
    .then((r) => r.json())
    .then(async (data) => {
      uiModule.showToast(`Project '${name}' created!`);
      await _fetchProjectsList();
      _currentProjectId = data.project.id;
      await _loadProjectDetail(_currentProjectId);
    })
    .catch((err) => uiModule.showError(err.message));
}

function _renderAddLinkPrompt(projectId) {
  const targetType = prompt('Enter link type (operations / email / calendar / document):', 'operations');
  if (!targetType) return;
  const targetId = prompt('Enter target identifier (e.g. bookings:1042, acc:INBOX:123, cal_event_uid, doc_id):');
  if (!targetId) return;
  const label = prompt('Enter a descriptive label:', targetId);

  fetch(`/api/projects/${projectId}/links`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      target_type: targetType.trim().toLowerCase(),
      target_id: targetId.trim(),
      label: label?.trim() || targetId.trim(),
    }),
  })
    .then((r) => r.json())
    .then(async () => {
      uiModule.showToast('Entity linked successfully!');
      await _loadProjectDetail(projectId);
    })
    .catch((err) => uiModule.showError(err.message));
}

function loggerError(err) {
  console.error('[Projects]', err);
}

// ---------------------------------------------------------------------------
// Public Exports
// ---------------------------------------------------------------------------

export function openProjects() {
  _injectStyles();
  _modal = _renderModalSkeleton();
  _open = true;
  // _renderModalSkeleton() builds the element with class="modal hidden" and
  // appends it to <body> itself; nothing else ever removed "hidden" — this
  // called Modals.show(), which modalManager.js has never exported (its
  // open/close primitives are register/toggle/close), so every open threw
  // before reaching _fetchProjectsList() and the panel never appeared.
  _modal.classList.remove('hidden');
  document.getElementById('tool-projects-btn')?.classList.add('active');
  
  _fetchProjectsList().then(() => {
    if (_currentProjectId) {
      _loadProjectDetail(_currentProjectId);
    }
  });
}

export function closeProjects() {
  _open = false;
  if (_modal) _modal.classList.add('hidden');
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
