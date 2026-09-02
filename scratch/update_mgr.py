import os

mgr_path = os.path.join('src', 'projects_manager.py')
with open(mgr_path, 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Update project_to_dict signature to accept include_pinned_notes
code = code.replace(
    "    include_content: bool = False,\n) -> Dict[str, Any]:",
    "    include_content: bool = False,\n    include_pinned_notes: bool = False,\n) -> Dict[str, Any]:"
)

# 2. Add agent_summary to dict
code = code.replace(
    '        "description": project.description,',
    '        "description": project.description,\n        "agent_summary": getattr(project, "agent_summary", None),'
)

# 3. Add pinned_notes fetch
notes_code = """
    if include_pinned_notes and db:
        from core.database import Note
        import json
        
        pinned = db.query(Note).filter(Note.project_id == project.id, Note.pinned == True).all()
        pinned_list = []
        for n in pinned:
            parsed_items = []
            if n.items:
                try:
                    parsed_items = json.loads(n.items)
                except Exception:
                    pass
            pinned_list.append({
                "id": n.id,
                "title": n.title,
                "content": n.content,
                "note_type": n.note_type,
                "items": parsed_items,
                "color": n.color,
                "pinned": n.pinned
            })
        data["pinned_notes"] = pinned_list
"""

if "data[\"pinned_notes\"] =" not in code:
    code = code.replace(
        '    if include_tasks:',
        notes_code + '\n    if include_tasks:'
    )

with open(mgr_path, 'w', encoding='utf-8') as f:
    f.write(code)

print("projects_manager.py updated.")
