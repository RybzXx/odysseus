import os

js_path = os.path.join('static', 'js', 'projects.js')
with open(js_path, 'r', encoding='utf-8') as f:
    code = f.read()

old_open = """export function openProjects() {
  _injectStyles();"""

new_open = """export function openProjects(projectId = null) {
  if (projectId) _currentProjectId = projectId;
  else _currentProjectId = null; // Force landing page on open
  
  _injectStyles();"""

if "Force landing page on open" not in code:
    code = code.replace(old_open, new_open)
    with open(js_path, 'w', encoding='utf-8') as f:
        f.write(code)
    print("Fixed openProjects")
