"""src/agent_tools/project_tools.py

Agent tool implementation for the Projects Module in Odysseus.
Exposes `manage_projects` to AI agents to query, create, update, manage tasks,
and attach cross-module links (operations keys, emails, calendar events, documents).
"""

import json
import logging
from typing import Any, Dict, Optional

from src.tool_utils import _parse_tool_args
from src.projects_manager import (
    create_project,
    save_project_content_to_disk,
    sync_project_disk_and_db,
    project_to_dict,
)
from core import database as cdb
from core.database import Project, ProjectTask, ProjectLink

logger = logging.getLogger(__name__)


class ManageProjectsTool:
    """Tool for managing project workspaces, tasks, and cross-module context."""

    name = "manage_projects"

    async def execute(self, content: str, owner: Optional[str] = None) -> Dict[str, Any]:
        try:
            args = _parse_tool_args(content)
        except ValueError:
            return {"error": "Invalid JSON arguments", "exit_code": 1}

        action = (args.get("action") or "list").strip().lower()
        project_id = (args.get("project_id") or args.get("id") or "").strip()

        db = cdb.SessionLocal()
        try:
            # ---------------------------------------------------------------
            # 1. LIST PROJECTS
            # ---------------------------------------------------------------
            if action == "list":
                q = db.query(Project)
                if owner:
                    q = q.filter((Project.owner == owner) | (Project.owner == None))
                status_filter = args.get("status")
                if status_filter and status_filter != "all":
                    q = q.filter(Project.status == status_filter)

                projects = q.order_by(Project.updated_at.desc()).all()
                return {
                    "projects": [
                        {
                            "id": p.id,
                            "slug": p.slug,
                            "name": p.name,
                            "status": p.status,
                            "priority": p.priority,
                            "task_total": p.task_total or 0,
                            "task_completed": p.task_completed or 0,
                            "folder_path": p.folder_path,
                            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                        }
                        for p in projects
                    ],
                    "count": len(projects),
                    "exit_code": 0,
                }

            # ---------------------------------------------------------------
            # 2. GET FULL PROJECT DETAIL
            # ---------------------------------------------------------------
            elif action == "get":
                if not project_id:
                    return {"error": "Missing required argument 'project_id'", "exit_code": 1}

                project = (
                    db.query(Project)
                    .filter((Project.id == project_id) | (Project.slug == project_id))
                    .first()
                )
                if not project:
                    return {"error": f"Project '{project_id}' not found", "exit_code": 1}

                return {
                    "project": project_to_dict(
                        project, db=db, include_tasks=True, include_links=True, include_content=True
                    ),
                    "exit_code": 0,
                }

            # ---------------------------------------------------------------
            # 3. GET COMPACT CONTEXT (FOR SYSTEM PROMPT / REASONING)
            # ---------------------------------------------------------------
            elif action in ("get_context", "context"):
                if not project_id:
                    return {"error": "Missing required argument 'project_id'", "exit_code": 1}

                project = (
                    db.query(Project)
                    .filter((Project.id == project_id) | (Project.slug == project_id))
                    .first()
                )
                if not project:
                    return {"error": f"Project '{project_id}' not found", "exit_code": 1}

                p_data = project_to_dict(project, db=db, include_tasks=True, include_links=True)
                
                # Format a compact, token-efficient text block for agent context
                lines = [
                    f"## Project: {project.name} (Status: {project.status}, Priority: {project.priority})",
                    f"Folder: `{project.folder_path}`",
                    "",
                    "### Tasks:",
                ]
                for t in p_data.get("tasks", []):
                    check = "[x]" if t["completed"] else "[ ]"
                    lines.append(f"- {check} (ID: {t['id']}) {t['title']}")

                if p_data.get("links"):
                    lines.append("\n### Linked Context:")
                    for l in p_data["links"]:
                        lines.append(f"- [{l['target_type'].upper()}] {l['label']} (ID: {l['target_id']})")

                return {
                    "context_text": "\n".join(lines),
                    "project_id": project.id,
                    "folder_path": project.folder_path,
                    "exit_code": 0,
                }

            # ---------------------------------------------------------------
            # 4. CREATE PROJECT
            # ---------------------------------------------------------------
            elif action in ("create", "add", "new"):
                name = args.get("name") or "New Project"
                slug = args.get("slug")
                description = args.get("description")
                priority = args.get("priority") or "normal"
                content = args.get("content")
                links = args.get("links")

                res = create_project(
                    name=name,
                    slug=slug,
                    description=description,
                    priority=priority,
                    owner=owner,
                    initial_content=content,
                    links=links,
                )
                return {"project": res, "message": f"Project '{name}' created successfully", "exit_code": 0}

            # ---------------------------------------------------------------
            # 5. UPDATE PROJECT CONTENT / METADATA
            # ---------------------------------------------------------------
            elif action in ("update", "save", "edit"):
                if not project_id:
                    return {"error": "Missing required argument 'project_id'", "exit_code": 1}

                project = (
                    db.query(Project)
                    .filter((Project.id == project_id) | (Project.slug == project_id))
                    .first()
                )
                if not project:
                    return {"error": f"Project '{project_id}' not found", "exit_code": 1}

                if "name" in args:
                    project.name = args["name"]
                if "status" in args:
                    project.status = args["status"]
                if "priority" in args:
                    project.priority = args["priority"]

                db.commit()

                content = args.get("content")
                if content is not None:
                    db.close()
                    res = save_project_content_to_disk(project.id, content, owner=owner)
                    return {"project": res, "message": "Project updated", "exit_code": 0}

                db.refresh(project)
                return {
                    "project": project_to_dict(project, db=db, include_tasks=True, include_links=True),
                    "exit_code": 0,
                }

            # ---------------------------------------------------------------
            # 6. ADD TASK
            # ---------------------------------------------------------------
            elif action == "add_task":
                if not project_id:
                    return {"error": "Missing required argument 'project_id'", "exit_code": 1}
                task_title = args.get("task_title") or args.get("title")
                if not task_title:
                    return {"error": "Missing required argument 'task_title'", "exit_code": 1}

                project = (
                    db.query(Project)
                    .filter((Project.id == project_id) | (Project.slug == project_id))
                    .first()
                )
                if not project:
                    return {"error": f"Project '{project_id}' not found", "exit_code": 1}

                task_count = db.query(ProjectTask).filter(ProjectTask.project_id == project.id).count()
                import uuid as _uuid
                task = ProjectTask(
                    id=f"ptask_{_uuid.uuid4().hex[:8]}",
                    project_id=project.id,
                    title=task_title.strip(),
                    completed=bool(args.get("completed", False)),
                    sort_order=task_count,
                    due_date=args.get("due_date"),
                )
                db.add(task)
                project.task_total = (project.task_total or 0) + 1
                if task.completed:
                    project.task_completed = (project.task_completed or 0) + 1

                db.commit()
                return {
                    "task": {
                        "id": task.id,
                        "title": task.title,
                        "completed": task.completed,
                        "sort_order": task.sort_order,
                    },
                    "exit_code": 0,
                }

            # ---------------------------------------------------------------
            # 7. TOGGLE TASK
            # ---------------------------------------------------------------
            elif action in ("toggle_task", "complete_task"):
                task_id = args.get("task_id")
                if not task_id:
                    return {"error": "Missing required argument 'task_id'", "exit_code": 1}

                task = db.query(ProjectTask).filter(ProjectTask.id == task_id).first()
                if not task:
                    return {"error": f"Task '{task_id}' not found", "exit_code": 1}

                project = db.query(Project).filter(Project.id == task.project_id).first()

                new_state = args.get("completed")
                if new_state is None:
                    new_state = not task.completed

                task.completed = bool(new_state)
                if project:
                    if task.completed:
                        project.task_completed = (project.task_completed or 0) + 1
                    else:
                        project.task_completed = max(0, (project.task_completed or 0) - 1)

                db.commit()
                return {
                    "task": {
                        "id": task.id,
                        "title": task.title,
                        "completed": task.completed,
                    },
                    "exit_code": 0,
                }

            # ---------------------------------------------------------------
            # 8. LINK ITEM
            # ---------------------------------------------------------------
            elif action == "link_item":
                if not project_id:
                    return {"error": "Missing required argument 'project_id'", "exit_code": 1}
                link_type = args.get("link_type") or args.get("target_type")
                link_target = args.get("link_target") or args.get("target_id")
                if not link_type or not link_target:
                    return {"error": "Missing 'link_type' or 'link_target'", "exit_code": 1}

                project = (
                    db.query(Project)
                    .filter((Project.id == project_id) | (Project.slug == project_id))
                    .first()
                )
                if not project:
                    return {"error": f"Project '{project_id}' not found", "exit_code": 1}

                import uuid as _uuid
                link = ProjectLink(
                    id=f"plink_{_uuid.uuid4().hex[:8]}",
                    project_id=project.id,
                    target_type=link_type,
                    target_id=link_target.strip(),
                    label=args.get("link_label") or args.get("label"),
                    metadata_json=args.get("metadata") or {},
                )
                db.add(link)
                db.commit()
                return {
                    "link": {
                        "id": link.id,
                        "target_type": link.target_type,
                        "target_id": link.target_id,
                        "label": link.label,
                    },
                    "exit_code": 0,
                }

            else:
                return {
                    "error": f"Unknown action '{action}'. Valid actions: list, get, get_context, create, update, add_task, toggle_task, link_item",
                    "exit_code": 1,
                }
        finally:
            if db.is_active:
                db.close()
