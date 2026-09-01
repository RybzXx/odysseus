"""routes/projects/projects_routes.py

REST API endpoints for the Hybrid Projects Module in Odysseus.
Exposes project lifecycle operations, task management, cross-module links,
and bidirectional disk-sync to the Odysseus UI and agent services.
"""

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from core import database as cdb
from core.database import Project, ProjectTask, ProjectLink, Session, ModelEndpoint
from src.auth_helpers import get_current_user
from src.projects_manager import (
    create_project,
    save_project_content_to_disk,
    sync_project_disk_and_db,
    sync_tasks_to_manifest_file,
    project_to_dict,
    get_project_structure_and_spec,
    parse_project_manifest,
    serialize_project_manifest,
    append_project_execution_log,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class ProjectCreateRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = "normal"
    content: Optional[str] = None
    links: Optional[List[Dict[str, Any]]] = None


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    status_reason: Optional[str] = None
    priority: Optional[str] = None
    content: Optional[str] = None


class ProjectSummarizeRequest(BaseModel):
    model: Optional[str] = None
    endpoint_url: Optional[str] = None


class TaskCreateRequest(BaseModel):
    title: str
    completed: Optional[bool] = False
    due_date: Optional[str] = None


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    completed: Optional[bool] = None
    due_date: Optional[str] = None


class LinkCreateRequest(BaseModel):
    target_type: str  # "operations" | "email" | "calendar" | "document"
    target_id: str
    label: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class TaskSessionRequest(BaseModel):
    task_id: Optional[str] = None
    task_title: Optional[str] = None


# ---------------------------------------------------------------------------
# Router Definition
# ---------------------------------------------------------------------------

def setup_projects_routes() -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["projects"])

    @router.get("")
    def list_projects(
        request: Request,
        status: Optional[str] = None,
        query: Optional[str] = None,
    ):
        """List all projects for the current user/admin."""
        owner = get_current_user(request)
        db = cdb.SessionLocal()
        try:
            q = db.query(Project)
            if owner:
                q = q.filter((Project.owner == owner) | (Project.owner == None))
            if status and status != "all":
                q = q.filter(Project.status == status)
            from sqlalchemy import case
            status_order = case(
                (Project.status == "active", 0),
                (Project.status == "on-hold", 1),
                (Project.status == "paused", 1),
                (Project.status == "halted", 2),
                (Project.status == "archived", 2),
                else_=3
            )
            projects = q.order_by(status_order.asc(), Project.updated_at.desc()).all()
            return {"projects": [project_to_dict(p, db=db, include_tasks=False, include_links=False, include_pinned_notes=True) for p in projects]}
        finally:
            db.close()

    @router.post("")
    def create_new_project(request: Request, body: ProjectCreateRequest):
        """Create a new project workspace and scaffold directory."""
        owner = get_current_user(request)
        try:
            result = create_project(
                name=body.name,
                slug=body.slug,
                description=body.description,
                priority=body.priority or "normal",
                owner=owner,
                initial_content=body.content,
                links=body.links,
            )
            return {"project": result}
        except Exception as e:
            logger.error(f"Failed to create project: {e}", exc_info=True)
            raise HTTPException(500, f"Failed to create project: {str(e)}")

    @router.get("/{project_id}")
    def get_project(request: Request, project_id: str):
        """Get full project details with tasks, resolved links, and raw content."""
        db = cdb.SessionLocal()
        try:
            project = (
                db.query(Project)
                .filter((Project.id == project_id) | (Project.slug == project_id))
                .first()
            )
            if not project:
                raise HTTPException(404, f"Project {project_id} not found")
            return {"project": project_to_dict(project, db=db, include_tasks=True, include_links=True, include_content=True)}
        finally:
            db.close()

    @router.get("/{project_id}/structure")
    def get_project_structure(request: Request, project_id: str):
        """Get file tree topology, tech stack analysis, and spec file content."""
        db = cdb.SessionLocal()
        try:
            project = (
                db.query(Project)
                .filter((Project.id == project_id) | (Project.slug == project_id))
                .first()
            )
            if not project:
                raise HTTPException(404, f"Project {project_id} not found")
            return get_project_structure_and_spec(project.id, db=db)
        finally:
            db.close()

    @router.put("/{project_id}")
    def update_project(request: Request, project_id: str, body: ProjectUpdateRequest):
        """Update project metadata or raw content and write back to disk."""
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

            if body.name is not None:
                project.name = body.name.strip()
            if body.description is not None:
                project.description = body.description
            if body.status is not None:
                project.status = body.status.lower().strip()
                if project.status == "active":
                    project.status_reason = None
            if body.status_reason is not None and project.status != "active":
                project.status_reason = body.status_reason.strip() or None
            if body.priority is not None:
                project.priority = body.priority.lower().strip()

            db.commit()

            # Sync frontmatter to PROJECT.md if manifest exists
            if project.manifest_path and Path(project.manifest_path).exists():
                try:
                    raw_text = Path(project.manifest_path).read_text(encoding="utf-8")
                    meta, md_body = parse_project_manifest(raw_text)
                    meta["name"] = project.name
                    meta["status"] = project.status
                    if project.status_reason:
                        meta["status_reason"] = project.status_reason
                    elif "status_reason" in meta:
                        del meta["status_reason"]
                    meta["priority"] = project.priority
                    Path(project.manifest_path).write_text(serialize_project_manifest(meta, md_body), encoding="utf-8")
                except Exception as e:
                    logger.warning(f"Failed to sync metadata to PROJECT.md: {e}")

            if body.content is not None:
                result = save_project_content_to_disk(project.id, body.content, owner=owner)
                return {"project": result}

            db.refresh(project)
            return {"project": project_to_dict(project, db=db, include_tasks=True, include_links=True, include_content=True)}
        finally:
            db.close()

    @router.post("/{project_id}/summarize")
    async def summarize_project(request: Request, project_id: str, body: Optional[ProjectSummarizeRequest] = None):
        """Generate an AI summary using the selected model, with robust fallback."""
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

            manifest_content = ""
            if project.manifest_path and Path(project.manifest_path).exists():
                try:
                    manifest_content = Path(project.manifest_path).read_text(encoding="utf-8")
                except Exception:
                    manifest_content = ""

            model_used = "heuristic-extractor"
            summary_text = None
            llm_error = None

            req_model = body.model if body else None
            req_url = body.endpoint_url if body else None

            if req_model and req_url:
                try:
                    from src.llm_core import llm_call_async
                    from src.endpoint_resolver import build_headers, normalize_base, resolve_endpoint_runtime

                    headers = None
                    try:
                        endpoints = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()
                        target_base = normalize_base(req_url)
                        for ep in endpoints:
                            ep_base, api_key = resolve_endpoint_runtime(ep, owner=owner)
                            if normalize_base(ep_base) == target_base or ep.base_url == req_url:
                                headers = build_headers(api_key, ep_base)
                                break
                    except Exception as he:
                        logger.debug(f"Could not resolve headers for endpoint {req_url}: {he}")

                    prompt = (
                        "You are an expert technical product manager. Provide a concise 2-sentence executive summary of this project for display on a project dashboard. "
                        "Focus on what it is, its core tech stack, and primary goal. Return ONLY the plain summary text without quotes, markdown headers, or chat filler.\n\n"
                        f"Project Name: {project.name}\n"
                        f"Project Content:\n{manifest_content[:3000]}"
                    )
                    messages = [{"role": "user", "content": prompt}]
                    summary_res = await llm_call_async(url=req_url, model=req_model, messages=messages, headers=headers, timeout=30)
                    if isinstance(summary_res, tuple):
                        summary_res = summary_res[0]
                    if summary_res and summary_res.strip():
                        summary_text = summary_res.strip()
                        model_used = req_model
                except Exception as err:
                    llm_error = getattr(err, "detail", None) or str(err)
                    logger.warning(f"LLM summarize failed for {project.slug} with {req_model}: {err}")

            if not summary_text:
                struct = get_project_structure_and_spec(project.id, db=db)
                overview = struct.get("sections", {}).get("overview") or project.description or ""
                clean = re.sub(r"#+\s+.*", "", overview).strip()
                lines = [l.strip() for l in clean.splitlines() if l.strip()]
                summary_text = " ".join(lines[:3]) if lines else project.description

            if not summary_text:
                summary_text = f"{project.name} workspace."

            project.agent_summary = summary_text
            db.commit()
            db.refresh(project)

            # Record sequential execution entry in PROJECT.md and logs/
            status_tag = "completed" if (model_used != "heuristic-extractor" and not llm_error) else ("fallback" if llm_error else "completed")
            append_project_execution_log(
                project.id,
                "AI Summary Generation",
                summary_text,
                status=status_tag,
                model=model_used,
                db=db,
            )

            return {
                "ok": True,
                "project_id": project.id,
                "summary": project.agent_summary,
                "model_used": model_used,
                "llm_error": llm_error,
            }
        finally:
            db.close()

    @router.delete("/{project_id}")
    def delete_project(request: Request, project_id: str, delete_files: bool = Query(default=False)):
        """Delete project from database and optionally remove workspace folder."""
        db = cdb.SessionLocal()
        try:
            project = (
                db.query(Project)
                .filter((Project.id == project_id) | (Project.slug == project_id))
                .first()
            )
            if not project:
                raise HTTPException(404, f"Project {project_id} not found")

            folder = project.folder_path
            db.delete(project)
            db.commit()

            if delete_files and folder:
                import shutil
                try:
                    shutil.rmtree(folder, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"Could not delete folder {folder}: {e}")

            return {"ok": True, "deleted_id": project_id}
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # Tasks Endpoints
    # -----------------------------------------------------------------------

    @router.post("/{project_id}/tasks")
    def add_task(request: Request, project_id: str, body: TaskCreateRequest):
        """Add a task to a project and update PROJECT.md."""
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

            task_count = db.query(ProjectTask).filter(ProjectTask.project_id == project.id).count()
            task = ProjectTask(
                id=f"ptask_{uuid.uuid4().hex[:8]}",
                project_id=project.id,
                title=body.title.strip(),
                completed=body.completed or False,
                sort_order=task_count,
                due_date=body.due_date,
            )
            db.add(task)
            project.task_total = (project.task_total or 0) + 1
            if task.completed:
                project.task_completed = (project.task_completed or 0) + 1

            db.commit()
            db.refresh(task)
            sync_tasks_to_manifest_file(project.id, db=db)
            return {"task": {
                "id": task.id,
                "title": task.title,
                "completed": task.completed,
                "sort_order": task.sort_order,
                "due_date": task.due_date,
            }}
        finally:
            db.close()

    @router.patch("/{project_id}/tasks/{task_id}")
    def update_task(request: Request, project_id: str, task_id: str, body: TaskUpdateRequest):
        """Toggle completion or update task title/due date."""
        db = cdb.SessionLocal()
        try:
            task = (
                db.query(ProjectTask)
                .filter(ProjectTask.id == task_id)
                .first()
            )
            if not task:
                raise HTTPException(404, f"Task {task_id} not found")

            project = db.query(Project).filter(Project.id == task.project_id).first()

            if body.completed is not None and body.completed != task.completed:
                task.completed = body.completed
                if project:
                    if task.completed:
                        project.task_completed = (project.task_completed or 0) + 1
                    else:
                        project.task_completed = max(0, (project.task_completed or 0) - 1)

            if body.title is not None:
                task.title = body.title.strip()
            if body.due_date is not None:
                task.due_date = body.due_date

            db.commit()
            db.refresh(task)
            if project:
                sync_tasks_to_manifest_file(project.id, db=db)
            return {"task": {
                "id": task.id,
                "title": task.title,
                "completed": task.completed,
                "sort_order": task.sort_order,
                "due_date": task.due_date,
                "agent_session_id": task.agent_session_id,
            }}
        finally:
            db.close()

    @router.delete("/{project_id}/tasks/{task_id}")
    def delete_task(request: Request, project_id: str, task_id: str):
        """Delete a task item from a project."""
        db = cdb.SessionLocal()
        try:
            task = db.query(ProjectTask).filter(ProjectTask.id == task_id).first()
            if not task:
                raise HTTPException(404, f"Task {task_id} not found")

            project = db.query(Project).filter(Project.id == task.project_id).first()
            if project:
                project.task_total = max(0, (project.task_total or 0) - 1)
                if task.completed:
                    project.task_completed = max(0, (project.task_completed or 0) - 1)

            db.delete(task)
            db.commit()
            if project:
                sync_tasks_to_manifest_file(project.id, db=db)
            return {"ok": True}
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # Cross-Module Links Endpoints
    # -----------------------------------------------------------------------

    @router.post("/{project_id}/links")
    def add_link(request: Request, project_id: str, body: LinkCreateRequest):
        """Attach a cross-module reference (operations key, email, calendar event, document)."""
        db = cdb.SessionLocal()
        try:
            project = (
                db.query(Project)
                .filter((Project.id == project_id) | (Project.slug == project_id))
                .first()
            )
            if not project:
                raise HTTPException(404, f"Project {project_id} not found")

            link = ProjectLink(
                id=f"plink_{uuid.uuid4().hex[:8]}",
                project_id=project.id,
                target_type=body.target_type,
                target_id=body.target_id.strip(),
                label=body.label,
                metadata_json=body.metadata or {},
            )
            db.add(link)
            db.commit()
            db.refresh(link)
            return {"link": {
                "id": link.id,
                "target_type": link.target_type,
                "target_id": link.target_id,
                "label": link.label,
            }}
        finally:
            db.close()

    @router.delete("/{project_id}/links/{link_id}")
    def delete_link(request: Request, project_id: str, link_id: str):
        """Unlink an item from a project."""
        db = cdb.SessionLocal()
        try:
            link = db.query(ProjectLink).filter(ProjectLink.id == link_id).first()
            if not link:
                raise HTTPException(404, f"Link {link_id} not found")
            db.delete(link)
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    # -----------------------------------------------------------------------
    # Sync Endpoint
    # -----------------------------------------------------------------------

    @router.post("/{project_id}/sync")
    def sync_project(request: Request, project_id: str):
        """Force re-parse PROJECT.md from disk and synchronize database index."""
        owner = get_current_user(request)
        try:
            updated = sync_project_disk_and_db(project_id, owner=owner)
            return {"project": updated, "synced": True}
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            logger.error(f"Failed to sync project {project_id}: {e}", exc_info=True)
            raise HTTPException(500, f"Sync error: {str(e)}")

    # -----------------------------------------------------------------------
    # Agent Chat Spawn Endpoint
    # -----------------------------------------------------------------------

    @router.post("/{project_id}/agent_session")
    def create_project_agent_session(request: Request, project_id: str, body: Optional[TaskSessionRequest] = None):
        """Spawn a dedicated chat session pre-configured with the project or task context."""
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

            session_id = str(uuid.uuid4())
            session_name = f"Task: {body.task_title}" if (body and body.task_title) else f"Project: {project.name}"
            session = Session(
                id=session_id,
                name=session_name,
                endpoint_url="",
                model="",
                owner=owner,
                mode="agent",
                folder=project.slug,
            )
            db.add(session)
            db.flush()
            if body and body.task_id:
                task = db.query(ProjectTask).filter(ProjectTask.id == body.task_id).first()
                if task:
                    task.agent_session_id = session_id
            else:
                project.agent_session_id = session_id
            db.commit()

            return {"session_id": session_id, "project_id": project.id, "task_id": body.task_id if body else None}
        finally:
            db.close()

    return router
