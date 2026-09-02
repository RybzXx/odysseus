import os
import re

p = os.path.join('static', 'js', 'projects.js')
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Add _composerTitle and _composerBody
code = code.replace(
    "let _composerChecklistRows = [''];",
    "let _composerChecklistRows = [''];\nlet _composerTitle = '';\nlet _composerBody = '';"
)

# 2. Modify _renderTasksTab inputs to use these variables
code = code.replace(
    """<input id="proj-comp-title-input" type="text" class="proj-comp-title" placeholder="${_composerType === 'todo' ? 'Checklist Title (e.g. Sprint Launch Tasks)...' : 'Note Title (e.g. Architecture Decisions)...'}" />""",
    """<input id="proj-comp-title-input" type="text" class="proj-comp-title" placeholder="${_composerType === 'todo' ? 'Checklist Title (e.g. Sprint Launch Tasks)...' : 'Note Title (e.g. Architecture Decisions)...'}" value="${_esc(_composerTitle)}" />"""
)

code = code.replace(
    """<textarea id="proj-comp-body-input" class="proj-comp-body" placeholder="Note content..."></textarea>""",
    """<textarea id="proj-comp-body-input" class="proj-comp-body" placeholder="Note content...">${_esc(_composerBody)}</textarea>"""
)

# 3. Modify `_composerChecklistRows` rendering to also preserve values if re-rendered
# Actually, the rows already use `it` mapped from `_composerChecklistRows`.
code = code.replace(
    """<input type="text" class="proj-comp-row-input" placeholder="List item..." value="${_esc(it)}" />""",
    """<input type="text" class="proj-comp-row-input" placeholder="List item..." value="${_esc(it)}" />"""
) # No change needed, just making sure.

# 4. Create _saveComposerState function
save_func = """
function _saveComposerState(container) {
  const t = container.querySelector('#proj-comp-title-input');
  if (t) _composerTitle = t.value;
  const b = container.querySelector('#proj-comp-body-input');
  if (b) _composerBody = b.value;
  if (_composerType === 'todo') {
    const inputs = container.querySelectorAll('.proj-comp-row-input');
    _composerChecklistRows = Array.from(inputs).map(inp => inp.value);
    if (_composerChecklistRows.length === 0) _composerChecklistRows = [''];
  }
}
"""
code = code.replace(
    "function _wireTasksComposer(container) {",
    save_func + "\nfunction _wireTasksComposer(container) {"
)

# 5. Inject _saveComposerState before _renderTasksTab calls inside _wireTasksComposer
code = code.replace(
    "_composerType = pill.getAttribute('data-type');\n      _renderTasksTab(container);",
    "_saveComposerState(container);\n      _composerType = pill.getAttribute('data-type');\n      _renderTasksTab(container);"
)

code = code.replace(
    "_composerColor = dot.getAttribute('data-color');\n      _renderTasksTab(container);",
    "_saveComposerState(container);\n      _composerColor = dot.getAttribute('data-color');\n      _renderTasksTab(container);"
)

code = code.replace(
    "_composerPinned = !_composerPinned;\n      _renderTasksTab(container);",
    "_saveComposerState(container);\n      _composerPinned = !_composerPinned;\n      _renderTasksTab(container);"
)

code = code.replace(
    """_composerChecklistRows.push('');
      _renderTasksTab(container);
      setTimeout(() => {
        const inputs = container.querySelectorAll('.proj-comp-row-input');
        if (inputs.length) inputs[inputs.length - 1].focus();
      }, 30);""",
    """_saveComposerState(container);
      _composerChecklistRows.push('');
      _renderTasksTab(container);
      setTimeout(() => {
        const inputs = container.querySelectorAll('.proj-comp-row-input');
        if (inputs.length) inputs[inputs.length - 1].focus();
      }, 30);"""
)

code = code.replace(
    """_composerChecklistRows.splice(idx, 1);
        if (_composerChecklistRows.length === 0) _composerChecklistRows.push('');
        _renderTasksTab(container);""",
    """_saveComposerState(container);
        _composerChecklistRows.splice(idx, 1);
        if (_composerChecklistRows.length === 0) _composerChecklistRows.push('');
        _renderTasksTab(container);"""
)

# Reset title and body on Add
code = code.replace(
    """_composerAttachments = [];
    _composerChecklistRows = [''];
    _renderTasksTab(container);""",
    """_composerAttachments = [];
    _composerChecklistRows = [''];
    _composerTitle = '';
    _composerBody = '';
    _renderTasksTab(container);"""
)
code = code.replace(
    """_composerExpanded = false;
        _composerAttachments = [];
        _composerChecklistRows = [''];
        _renderTasksTab(container);""",
    """_composerExpanded = false;
        _composerAttachments = [];
        _composerChecklistRows = [''];
        _composerTitle = '';
        _composerBody = '';
        _renderTasksTab(container);"""
)


# 6. Add event listeners for `.proj-check-text` in `_wireNoteCards`
inline_edit_code = """
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
            if(window.uiModule) window.uiModule.showError(err.message);
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

"""
code = code.replace(
    "// Add checklist item inline on card",
    inline_edit_code + "\n  // Add checklist item inline on card"
)

# 7. Add confirmation before note deletion
code = code.replace(
    """  // Delete note card
  container.querySelectorAll('.proj-card-del-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const noteId = btn.getAttribute('data-id');
      const idx = _projectNotes.findIndex((n) => n.id === noteId);
      if (idx >= 0) {
        _projectNotes.splice(idx, 1);
        _renderTasksTab(container);
      }""",
    """  // Delete note card
  container.querySelectorAll('.proj-card-del-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm('Are you sure you want to delete this note?')) return;
      const noteId = btn.getAttribute('data-id');
      const idx = _projectNotes.findIndex((n) => n.id === noteId);
      if (idx >= 0) {
        _projectNotes.splice(idx, 1);
        _renderTasksTab(container);
      }"""
)

# 8. Fix loggerError call
code = code.replace("loggerError(", "console.error(") # Standardizing if loggerError is not defined elsewhere

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)

print("Bug fixes complete.")
