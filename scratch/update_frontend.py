import os

projects_js_path = os.path.join('static', 'js', 'projects.js')
with open(projects_js_path, 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Update _fetchProjectsList to not auto-select a project
code = code.replace(
    "_currentProjectId = _projects[0].id;",
    "_currentProjectId = null; // Default to landing page"
)

# 2. Add _renderLandingPage
landing_page_code = """
function _renderLandingPage() {
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

  if (_projects.length === 0) {
    container.innerHTML = `<div style="padding:40px; text-align:center; color:var(--fg-muted);">No projects found. Create one to get started!</div>`;
    return;
  }

  const cardsHtml = _projects.map(p => {
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

    return `
      <div class="proj-landing-card" style="background: var(--bg-elev, #222); border: 1px solid var(--border, #333); border-radius: 8px; padding: 16px; margin-bottom: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
          <h2 style="margin: 0 0 4px 0; font-size: 18px;">${_esc(p.name)}</h2>
          <button class="proj-btn primary proj-open-btn" data-id="${_esc(p.id)}">Open Workspace</button>
        </div>
        <div style="font-size: 12px; color: var(--fg-muted); margin-bottom: 12px;">Status: ${_esc(p.status)}</div>
        
        <div style="font-size: 13px; line-height: 1.5; color: var(--fg); margin-bottom: 12px;">
          ${_esc(p.agent_summary || p.description || 'No summary available.')}
        </div>
        
        <button class="proj-btn proj-summarize-btn" data-id="${_esc(p.id)}" style="font-size: 11px; margin-bottom: 8px;">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px;"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
          Auto-Summarize
        </button>

        ${pinnedHtml}
      </div>
    `;
  }).join('');

  container.innerHTML = `
    <div style="padding: 24px; max-width: 800px; margin: 0 auto;">
      <h1 style="margin-top:0; font-size: 24px; margin-bottom: 24px;">Project Workspaces</h1>
      ${cardsHtml}
    </div>
  `;

  // Wire events
  container.querySelectorAll('.proj-open-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _currentProjectId = btn.getAttribute('data-id');
      _loadProjectDetail(_currentProjectId);
    });
  });

  container.querySelectorAll('.proj-summarize-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-id');
      const originalText = btn.innerHTML;
      btn.innerHTML = 'Summarizing...';
      btn.disabled = true;
      try {
        await fetch(`/api/projects/${id}/summarize`, { method: 'POST' });
        await _fetchProjectsList();
        _renderLandingPage();
      } catch (err) {
        if(window.uiModule) window.uiModule.showError(err.message);
        btn.innerHTML = originalText;
        btn.disabled = false;
      }
    });
  });
}
"""

if "function _renderLandingPage" not in code:
    code = code.replace(
        "function _renderOverviewTab(container) {",
        landing_page_code + "\nfunction _renderOverviewTab(container) {"
    )

# 3. Update _loadProjectDetail to handle null
load_project_detail_old = """async function _loadProjectDetail(id, silent=false) {
  if (!id) return;
  _currentProjectId = id;"""

load_project_detail_new = """async function _loadProjectDetail(id, silent=false) {
  if (!id) {
    _renderLandingPage();
    return;
  }
  _currentProjectId = id;
  
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
"""

code = code.replace(load_project_detail_old, load_project_detail_new)

# 4. In openProjects(), if not current project, call _loadProjectDetail(null) (which renders landing page)
code = code.replace(
    """    if (_currentProjectId) {
      _loadProjectDetail(_currentProjectId);
    } else {
      _renderEmptyState();
    }""",
    """    if (_currentProjectId) {
      _loadProjectDetail(_currentProjectId);
    } else {
      _loadProjectDetail(null);
    }"""
)

with open(projects_js_path, 'w', encoding='utf-8') as f:
    f.write(code)

print("projects.js updated.")
