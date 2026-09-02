import os

p = os.path.join('static', 'js', 'projects.js')
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

# Fix search input losing state and focus
search_handler_old = """  const searchInput = container.querySelector('#proj-note-search');
  searchInput?.addEventListener('input', () => {
    _noteSearchQuery = searchInput.value;
    _renderTasksTab(container);
  });"""
  
search_handler_new = """  const searchInput = container.querySelector('#proj-note-search');
  searchInput?.addEventListener('input', () => {
    _saveComposerState(container);
    _noteSearchQuery = searchInput.value;
    _renderTasksTab(container);
    const newSearch = container.querySelector('#proj-note-search');
    if (newSearch) {
      newSearch.focus();
      newSearch.setSelectionRange(_noteSearchQuery.length, _noteSearchQuery.length);
    }
  });"""
code = code.replace(search_handler_old, search_handler_new)

# Fix filter pills losing state
filter_handler_old = """  container.querySelectorAll('.proj-filter-bar button[data-filter]').forEach((btn) => {
    btn.addEventListener('click', () => {
      _noteFilter = btn.getAttribute('data-filter');
      _renderTasksTab(container);
    });
  });"""
  
filter_handler_new = """  container.querySelectorAll('.proj-filter-bar button[data-filter]').forEach((btn) => {
    btn.addEventListener('click', () => {
      _saveComposerState(container);
      _noteFilter = btn.getAttribute('data-filter');
      _renderTasksTab(container);
    });
  });"""
code = code.replace(filter_handler_old, filter_handler_new)

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)

print("Fixed state loss on filters and search.")
