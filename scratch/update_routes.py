import os

projects_routes_path = os.path.join('routes', 'projects', 'projects_routes.py')
with open(projects_routes_path, 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Update list_projects to include pinned notes
code = code.replace(
    'return {"projects": [project_to_dict(p, db=db, include_tasks=False, include_links=False) for p in projects]}',
    'return {"projects": [project_to_dict(p, db=db, include_tasks=False, include_links=False, include_pinned_notes=True) for p in projects]}'
)

# 2. Add summarize endpoint
summarize_endpoint = """
    @router.post("/{project_id}/summarize")
    async def summarize_project(request: Request, project_id: str):
        \"\"\"Generate an AI summary of the project and save it to agent_summary.\"\"\"
        owner = get_current_user(request)
        db = cdb.SessionLocal()
        try:
            project = (
                db.query(Project)
                .filter((Project.id == project_id) | (Project.slug == project_id))
                .first()
            )
            if not project:
                raise HTTPException(404, f"Project {project_id} not found")

            # Fetch notes
            from core.database import Note
            import json
            notes = db.query(Note).filter(Note.project_id == project.id).all()
            
            # Read manifest
            import pathlib
            manifest_content = ""
            if project.manifest_path and pathlib.Path(project.manifest_path).exists():
                manifest_content = pathlib.Path(project.manifest_path).read_text(encoding='utf-8')

            # Build prompt
            prompt = f"Summarize the following project workspace in 2-3 concise sentences. Focus on the core objective and the current state.\n\nProject Name: {project.name}\nDescription: {project.description}\n\n"
            if manifest_content:
                # Truncate manifest if huge
                prompt += f"Manifest Snippet:\n{manifest_content[:1500]}\n\n"
            if notes:
                prompt += "Notes/Checklists:\n"
                for n in notes[:10]:
                    prompt += f"- {n.title} (Type: {n.note_type})\n"

            # Use LLM
            from src.endpoint_resolver import resolve_endpoint, build_chat_url, build_headers
            from src.llm_core import llm_call_async
            
            ep, ep_model, api_key = resolve_endpoint("utility", owner=owner)
            if not ep:
                ep, ep_model, api_key = resolve_endpoint("default", owner=owner)
            
            if not ep:
                raise HTTPException(400, "No utility or default LLM configured to generate summary.")

            url = build_chat_url(ep.base_url)
            headers = build_headers(ep.base_url, api_key)

            summary = await llm_call_async(
                url=url,
                model=ep_model or "gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                headers=headers,
                temperature=0.3,
                max_tokens=200
            )

            project.agent_summary = summary.strip()
            db.commit()

            return {"summary": project.agent_summary}
        except Exception as e:
            logger.error(f"Summarize failed: {e}", exc_info=True)
            raise HTTPException(500, str(e))
        finally:
            db.close()
"""
if "def summarize_project" not in code:
    code = code.replace(
        '    @router.post("")',
        summarize_endpoint + '\n    @router.post("")'
    )

with open(projects_routes_path, 'w', encoding='utf-8') as f:
    f.write(code)

print("projects_routes.py updated.")
