import os
import re

js_path = os.path.join('static', 'js', 'projects.js')
with open(js_path, 'r', encoding='utf-8') as f:
    code = f.read()

# Replace _loadProjectDetail correctly
old_func_start = """async function _loadProjectDetail(projectId, silent = false) {
  if (!projectId) {
    _renderEmptyState();
    return;
  }"""

new_func_start = """async function _loadProjectDetail(projectId, silent = false) {
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
"""

if "⬅ All Projects" not in code:
    code = code.replace(old_func_start, new_func_start)
    with open(js_path, 'w', encoding='utf-8') as f:
        f.write(code)
    print("Fixed _loadProjectDetail.")
else:
    print("Already fixed.")
