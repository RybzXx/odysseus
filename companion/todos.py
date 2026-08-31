"""companion/todos.py

Unified To-Do gateway helpers for companion clients and Android widgets.
Aggregates and normalizes to-do items from Google Keep-style Notes (checklist items)
and Projects (ProjectTasks) supporting bidirectional sync.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from core.database import Note, Project, ProjectTask

logger = logging.getLogger(__name__)


def _is_owner_match(row_owner: Optional[str], owner: Optional[str]) -> bool:
    """Check if row is owned by the user or shared (null owner)."""
    if owner is None:
        return True
    return row_owner is None or row_owner == owner


def fetch_all_todos(
    db: Session,
    owner: Optional[str] = None,
    include_completed: bool = False,
    source: str = "all",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    # 1. Notes Module
    if source in ("all", "notes", "note"):
        note_q = db.query(Note).filter(Note.archived == False)
        if owner is not None:
            note_q = note_q.filter((Note.owner == owner) | (Note.owner == None))
        notes = note_q.order_by(Note.pinned.desc(), Note.updated_at.desc()).all()

        for note in notes:
            if not _is_owner_match(note.owner, owner):
                continue
            raw_items = note.items
            parsed_items = []
            if raw_items:
                try:
                    parsed_items = json.loads(raw_items) if isinstance(raw_items, str) else raw_items
                except (ValueError, TypeError):
                    parsed_items = []

            if isinstance(parsed_items, list) and parsed_items:
                for idx, item in enumerate(parsed_items):
                    if not isinstance(item, dict):
                        continue
                    is_done = bool(item.get("done") or item.get("checked"))
                    if not include_completed and is_done:
                        continue
                    item_id_key = str(item.get("id") or idx)
                    item_title = str(item.get("text") or "").strip()
                    if not item_title:
                        continue
                    items.append({
                        "id": f"note:{note.id}:{item_id_key}",
                        "source_type": "note",
                        "source_id": note.id,
                        "source_title": (note.title or "Note").strip() or "Note",
                        "title": item_title,
                        "completed": is_done,
                        "due_date": note.due_date,
                        "sort_order": idx,
                        "updated_at": note.updated_at.isoformat() if note.updated_at else (
                            note.created_at.isoformat() if note.created_at else None
                        ),
                    })

    # 2. Projects Module
    if source in ("all", "projects", "project"):
        proj_q = db.query(Project)
        if owner is not None:
            proj_q = proj_q.filter((Project.owner == owner) | (Project.owner == None))
        projects = proj_q.all()
        proj_map = {p.id: p for p in projects if _is_owner_match(p.owner, owner)}

        if proj_map:
            task_q = db.query(ProjectTask).filter(ProjectTask.project_id.in_(list(proj_map.keys())))
            if not include_completed:
                task_q = task_q.filter(ProjectTask.completed == False)
            tasks = task_q.order_by(ProjectTask.completed.asc(), ProjectTask.sort_order.asc(), ProjectTask.updated_at.desc()).all()

            for task in tasks:
                proj = proj_map.get(task.project_id)
                if not proj:
                    continue
                items.append({
                    "id": f"project:{proj.id}:{task.id}",
                    "source_type": "project",
                    "source_id": proj.id,
                    "source_title": (proj.name or "Project").strip(),
                    "title": (task.title or "").strip(),
                    "completed": bool(task.completed),
                    "due_date": task.due_date,
                    "sort_order": task.sort_order or 0,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                })

    items.sort(key=lambda x: (1 if x.get("completed") else 0, -(len(x.get("updated_at") or "")), x.get("updated_at") or ""))
    return items[:limit]


def toggle_todo(
    db: Session,
    owner: Optional[str],
    item_id: str,
    completed: Optional[bool] = None,
) -> Dict[str, Any]:
    parts = item_id.split(":", 2)
    if len(parts) < 3:
        raise ValueError(f"Invalid todo item id format: {item_id}")

    kind, parent_id, child_key = parts[0], parts[1], parts[2]
    now_iso = datetime.now(timezone.utc).isoformat()

    if kind == "note":
        note = db.query(Note).filter(Note.id == parent_id).first()
        if not note:
            raise LookupError(f"Note {parent_id} not found")
        if not _is_owner_match(note.owner, owner):
            raise PermissionError("Forbidden")

        raw_items = note.items
        parsed_items = []
        if raw_items:
            try:
                parsed_items = json.loads(raw_items) if isinstance(raw_items, str) else list(raw_items)
            except (ValueError, TypeError):
                parsed_items = []

        found = False
        target_completed = False
        for idx, it in enumerate(parsed_items):
            if not isinstance(it, dict):
                continue
            cur_id = str(it.get("id") or idx)
            if cur_id == child_key or str(idx) == child_key:
                cur_state = bool(it.get("done") or it.get("checked"))
                target_completed = (not cur_state) if completed is None else bool(completed)
                it["done"] = target_completed
                it["checked"] = target_completed
                found = True
                break

        if not found:
            raise LookupError(f"Checklist item {child_key} not found in note {parent_id}")

        note.items = json.dumps(parsed_items)
        flag_modified(note, "items")
        note.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(note)
        return {
            "ok": True,
            "id": item_id,
            "completed": target_completed,
            "updated_at": note.updated_at.isoformat() if note.updated_at else now_iso,
        }

    elif kind == "project":
        task = db.query(ProjectTask).filter(ProjectTask.id == child_key, ProjectTask.project_id == parent_id).first()
        if not task:
            raise LookupError(f"Project task {child_key} not found")

        project = db.query(Project).filter(Project.id == parent_id).first()
        if project and not _is_owner_match(project.owner, owner):
            raise PermissionError("Forbidden")

        cur_state = bool(task.completed)
        target_completed = (not cur_state) if completed is None else bool(completed)
        task.completed = target_completed
        task.updated_at = datetime.now(timezone.utc)

        if project and target_completed != cur_state:
            if target_completed:
                project.task_completed = (project.task_completed or 0) + 1
            else:
                project.task_completed = max(0, (project.task_completed or 0) - 1)

        db.commit()
        db.refresh(task)

        if project:
            try:
                from src.projects_manager import sync_tasks_to_manifest_file
                sync_tasks_to_manifest_file(project.id, db=db)
            except Exception as e:
                logger.debug(f"Manifest sync deferred: {e}")

        return {
            "ok": True,
            "id": item_id,
            "completed": target_completed,
            "updated_at": task.updated_at.isoformat() if task.updated_at else now_iso,
        }

    else:
        raise ValueError(f"Unknown todo source kind: {kind}")


def create_todo(
    db: Session,
    owner: Optional[str],
    title: str,
    target_type: str = "note",
    target_id: Optional[str] = None,
    due_date: Optional[str] = None,
) -> Dict[str, Any]:
    title_clean = title.strip()
    if not title_clean:
        raise ValueError("Task title cannot be empty")

    now_iso = datetime.now(timezone.utc).isoformat()

    if target_type in ("project", "projects"):
        project = None
        if target_id:
            project = db.query(Project).filter((Project.id == target_id) | (Project.slug == target_id)).first()
        else:
            proj_q = db.query(Project)
            if owner:
                proj_q = proj_q.filter((Project.owner == owner) | (Project.owner == None))
            project = proj_q.order_by(Project.updated_at.desc()).first()

        if not project:
            proj_hex = uuid.uuid4().hex[:8]
            slug = f"general-tasks-{proj_hex}"
            project = Project(
                id=f"proj_{proj_hex}",
                slug=slug,
                name="General Tasks",
                owner=owner,
                status="active",
                folder_path=f"workspaces/{slug}",
                manifest_path=f"workspaces/{slug}/PROJECT.md",
                task_total=0,
                task_completed=0,
            )
            db.add(project)
            db.commit()
            db.refresh(project)

        if not _is_owner_match(project.owner, owner):
            raise PermissionError("Forbidden")

        task_count = db.query(ProjectTask).filter(ProjectTask.project_id == project.id).count()
        task = ProjectTask(
            id=f"ptask_{uuid.uuid4().hex[:8]}",
            project_id=project.id,
            title=title_clean,
            completed=False,
            sort_order=task_count,
            due_date=due_date,
        )
        db.add(task)
        project.task_total = (project.task_total or 0) + 1
        db.commit()
        db.refresh(task)

        try:
            from src.projects_manager import sync_tasks_to_manifest_file
            sync_tasks_to_manifest_file(project.id, db=db)
        except Exception as e:
            logger.debug(f"Manifest sync deferred: {e}")

        return {
            "ok": True,
            "item": {
                "id": f"project:{project.id}:{task.id}",
                "source_type": "project",
                "source_id": project.id,
                "source_title": project.name,
                "title": task.title,
                "completed": False,
                "due_date": task.due_date,
                "sort_order": task.sort_order,
                "updated_at": task.updated_at.isoformat() if task.updated_at else now_iso,
            },
        }

    else:
        note = None
        if target_id:
            note = db.query(Note).filter(Note.id == target_id).first()
        else:
            note_q = db.query(Note).filter(Note.note_type == "checklist", Note.archived == False)
            if owner:
                note_q = note_q.filter((Note.owner == owner) | (Note.owner == None))
            note = note_q.order_by(Note.pinned.desc(), Note.updated_at.desc()).first()

        new_item_id = uuid.uuid4().hex[:8]
        new_item = {
            "id": new_item_id,
            "text": title_clean,
            "done": False,
            "checked": False,
        }

        if not note:
            note = Note(
                id=str(uuid.uuid4()),
                owner=owner,
                title="Quick Tasks",
                note_type="checklist",
                items=json.dumps([new_item]),
                due_date=due_date,
            )
            db.add(note)
            db.commit()
            db.refresh(note)
            items_list = [new_item]
        else:
            if not _is_owner_match(note.owner, owner):
                raise PermissionError("Forbidden")
            raw_items = note.items
            items_list = []
            if raw_items:
                try:
                    items_list = json.loads(raw_items) if isinstance(raw_items, str) else list(raw_items)
                except (ValueError, TypeError):
                    items_list = []
            items_list.append(new_item)
            note.items = json.dumps(items_list)
            flag_modified(note, "items")
            note.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(note)

        return {
            "ok": True,
            "item": {
                "id": f"note:{note.id}:{new_item_id}",
                "source_type": "note",
                "source_id": note.id,
                "source_title": note.title or "Quick Tasks",
                "title": title_clean,
                "completed": False,
                "due_date": note.due_date,
                "sort_order": len(items_list) - 1,
                "updated_at": note.updated_at.isoformat() if note.updated_at else now_iso,
            },
        }
