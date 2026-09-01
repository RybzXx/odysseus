"""src/projects_manager.py

Hybrid Projects Manager for Odysseus:
- Manages project workspaces on disk (<workspace_root>/projects/<slug>/)
- Parses and serializes PROJECT.md files with YAML frontmatter + Markdown body
- Maintains bidirectional synchronization between disk files and SQLite index
- Resolves polymorphic cross-module links (Operations worklist, Email, Calendar, Documents)
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None

from core import database as cdb
from core.database import Project, ProjectTask, ProjectLink, Document, Note, CalendarEvent, OperationsNote
from src.constants import DATA_DIR

logger = logging.getLogger(__name__)

DEFAULT_PROJECTS_DIR = Path(DATA_DIR) / "projects"


def get_projects_root() -> Path:
    """Return the root directory where project workspaces are stored."""
    root = DEFAULT_PROJECTS_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def slugify(text: str) -> str:
    """Convert text into a URL/filesystem friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "project"


# ---------------------------------------------------------------------------
# YAML Frontmatter Parser / Serializer
# ---------------------------------------------------------------------------

def parse_project_manifest(text: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter enclosed in `---` and return (metadata, body)."""
    text = text.strip()
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    raw_yaml = parts[1].strip()
    body = parts[2].lstrip("\r\n")

    if yaml is not None:
        try:
            metadata = yaml.safe_load(raw_yaml) or {}
            if isinstance(metadata, dict):
                return metadata, body
        except Exception as e:
            logger.warning(f"Failed to parse YAML with pyyaml: {e}")

    # Fallback key-value parser if pyyaml is missing or fails
    metadata = {}
    for line in raw_yaml.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if v.lower() == "true":
                v = True
            elif v.lower() == "false":
                v = False
            metadata[k] = v

    return metadata, body


def serialize_project_manifest(metadata: Dict[str, Any], body: str) -> str:
    """Serialize metadata into YAML frontmatter followed by markdown body."""
    clean_meta = {k: v for k, v in metadata.items() if v is not None}
    if yaml is not None:
        yaml_str = yaml.dump(clean_meta, default_flow_style=False, sort_keys=False, allow_unicode=True)
        return f"---\n{yaml_str.strip()}\n---\n\n{body.strip()}\n"

    # Fallback serializer
    lines = ["---"]
    for k, v in clean_meta.items():
        if isinstance(v, (list, dict)):
            lines.append(f"{k}: {json.dumps(v)}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(body.strip())
    lines.append("")
    return "\n".join(lines)


def parse_tasks_from_markdown(body: str) -> List[Dict[str, Any]]:
    """Extract `- [ ]` and `- [x]` checklist items from the markdown body."""
    tasks = []
    lines = body.splitlines()
    sort_order = 0
    for line in lines:
        match = re.match(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)$", line)
        if match:
            done = match.group(1).lower() == "x"
            title = match.group(2).strip()
            if title:
                tasks.append({
                    "title": title,
                    "completed": done,
                    "sort_order": sort_order,
                })
                sort_order += 1
    return tasks


# ---------------------------------------------------------------------------
# Project Scaffolding & CRUD
# ---------------------------------------------------------------------------

def create_project(
    name: str,
    slug: Optional[str] = None,
    description: Optional[str] = None,
    priority: str = "normal",
    owner: Optional[str] = None,
    initial_content: Optional[str] = None,
    links: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create a new project workspace on disk and register in SQLite."""
    proj_id = f"proj_{uuid.uuid4().hex[:8]}"
    clean_slug = slugify(slug or name)
    
    projects_root = get_projects_root()
    folder_path = projects_root / clean_slug
    
    counter = 1
    orig_slug = clean_slug
    while folder_path.exists():
        clean_slug = f"{orig_slug}-{counter}"
        folder_path = projects_root / clean_slug
        counter += 1

    folder_path.mkdir(parents=True, exist_ok=True)
    (folder_path / "docs").mkdir(exist_ok=True)
    (folder_path / "tasks").mkdir(exist_ok=True)
    (folder_path / "logs").mkdir(exist_ok=True)

    manifest_path = folder_path / "PROJECT.md"

    now_iso = datetime.now(timezone.utc).isoformat()
    metadata = {
        "id": proj_id,
        "name": name,
        "slug": clean_slug,
        "status": "active",
        "priority": priority,
        "owner": owner,
        "created_at": now_iso,
        "updated_at": now_iso,
        "links": links or [],
    }

    body = initial_content or (
        f"# {name}\n\n"
        f"{description or 'Project workspace and shared agent context.'}\n\n"
        f"## Objectives\n- Define project scope and deliverables.\n\n"
        f"## Active Tasks\n- [ ] Initial project setup\n- [ ] Review documentation and links\n\n"
        f"## Execution Log\n- *{now_iso} (System)*: Project initialized.\n"
    )

    manifest_content = serialize_project_manifest(metadata, body)
    manifest_path.write_text(manifest_content, encoding="utf-8")

    db = cdb.SessionLocal()
    try:
        project = Project(
            id=proj_id,
            slug=clean_slug,
            name=name,
            description=description,
            status="active",
            priority=priority,
            owner=owner,
            folder_path=str(folder_path),
            manifest_path=str(manifest_path),
            task_total=2,
            task_completed=0,
        )
        db.add(project)

        parsed_tasks = parse_tasks_from_markdown(body)
        for t in parsed_tasks:
            task = ProjectTask(
                id=f"ptask_{uuid.uuid4().hex[:8]}",
                project_id=proj_id,
                title=t["title"],
                completed=t["completed"],
                sort_order=t["sort_order"],
            )
            db.add(task)

        if links:
            for l in links:
                link = ProjectLink(
                    id=f"plink_{uuid.uuid4().hex[:8]}",
                    project_id=proj_id,
                    target_type=l.get("type") or l.get("target_type", "document"),
                    target_id=str(l.get("key") or l.get("id") or l.get("target_id", "")),
                    label=l.get("label") or l.get("title") or l.get("summary", ""),
                    metadata_json=l,
                )
                db.add(link)

        db.commit()
        db.refresh(project)
        return project_to_dict(project, db=db, include_tasks=True, include_links=True)
    finally:
        db.close()


def sync_project_disk_and_db(project_id_or_slug: str, owner: Optional[str] = None) -> Dict[str, Any]:
    """Re-parse PROJECT.md from disk and synchronize the SQLite index."""
    db = cdb.SessionLocal()
    try:
        project = (
            db.query(Project)
            .filter((Project.id == project_id_or_slug) | (Project.slug == project_id_or_slug))
            .first()
        )
        if not project:
            raise FileNotFoundError(f"Project {project_id_or_slug} not found in database.")

        manifest_file = Path(project.manifest_path)
        if not manifest_file.exists():
            raise FileNotFoundError(f"PROJECT.md missing at {project.manifest_path}")

        raw_text = manifest_file.read_text(encoding="utf-8")
        metadata, body = parse_project_manifest(raw_text)

        if "name" in metadata:
            project.name = metadata["name"]
        if "status" in metadata:
            project.status = metadata["status"]
        if "status_reason" in metadata:
            project.status_reason = metadata["status_reason"]
        if "priority" in metadata:
            project.priority = metadata["priority"]

        disk_tasks = parse_tasks_from_markdown(body)
        existing_tasks = {t.title.strip().lower(): t for t in project.tasks}
        
        db.query(ProjectTask).filter(ProjectTask.project_id == project.id).delete()
        
        total_tasks = len(disk_tasks)
        completed_tasks = 0

        for idx, dt in enumerate(disk_tasks):
            t_title = dt["title"]
            is_done = dt["completed"]
            if is_done:
                completed_tasks += 1

            old_task = existing_tasks.get(t_title.strip().lower())
            task = ProjectTask(
                id=old_task.id if old_task else f"ptask_{uuid.uuid4().hex[:8]}",
                project_id=project.id,
                title=t_title,
                completed=is_done,
                sort_order=idx,
                due_date=old_task.due_date if old_task else None,
                agent_session_id=old_task.agent_session_id if old_task else None,
            )
            db.add(task)

        project.task_total = total_tasks
        project.task_completed = completed_tasks

        raw_links = metadata.get("links", [])
        if isinstance(raw_links, list):
            db.query(ProjectLink).filter(ProjectLink.project_id == project.id).delete()
            for l in raw_links:
                if isinstance(l, dict):
                    link = ProjectLink(
                        id=f"plink_{uuid.uuid4().hex[:8]}",
                        project_id=project.id,
                        target_type=l.get("type") or l.get("target_type", "document"),
                        target_id=str(l.get("key") or l.get("id") or l.get("target_id", "")),
                        label=l.get("label") or l.get("title") or l.get("summary", ""),
                        metadata_json=l,
                    )
                    db.add(link)

        db.commit()
        db.refresh(project)
        return project_to_dict(project, db=db, include_tasks=True, include_links=True)
    finally:
        db.close()


def save_project_content_to_disk(project_id: str, content: str, owner: Optional[str] = None) -> Dict[str, Any]:
    """Write updated markdown body / manifest content to PROJECT.md and re-sync."""
    db = cdb.SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found.")

        manifest_path = Path(project.manifest_path)
        metadata, body = parse_project_manifest(content)
        
        if not metadata and manifest_path.exists():
            existing_meta, _ = parse_project_manifest(manifest_path.read_text(encoding="utf-8"))
            metadata = existing_meta
            body = content

        metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
        manifest_text = serialize_project_manifest(metadata, body)
        manifest_path.write_text(manifest_text, encoding="utf-8")

        db.close()
        return sync_project_disk_and_db(project_id, owner=owner)
    finally:
        if db.is_active:
            db.close()


def sync_tasks_to_manifest_file(project_id: str, db=None) -> None:
    """Rewrite the tasks section in PROJECT.md to match current database tasks."""
    close_db = False
    if db is None:
        db = cdb.SessionLocal()
        close_db = True
    try:
        project = db.query(Project).filter((Project.id == project_id) | (Project.slug == project_id)).first()
        if not project or not project.manifest_path:
            return
        manifest_path = Path(project.manifest_path)
        if not manifest_path.exists():
            return
        raw_text = manifest_path.read_text(encoding="utf-8")
        metadata, body = parse_project_manifest(raw_text)

        tasks = (
            db.query(ProjectTask)
            .filter(ProjectTask.project_id == project.id)
            .order_by(ProjectTask.sort_order.asc())
            .all()
        )
        task_lines = []
        for t in tasks:
            mark = "x" if t.completed else " "
            task_lines.append(f"- [{mark}] {t.title}")

        task_block = "\n".join(task_lines)
        if re.search(r"^## Active Tasks.*?(?=^## |\Z)", body, flags=re.MULTILINE | re.DOTALL):
            body = re.sub(
                r"^## Active Tasks.*?(?=^## |\Z)",
                f"## Active Tasks\n{task_block}\n\n",
                body,
                flags=re.MULTILINE | re.DOTALL,
            )
        else:
            body = f"{body.strip()}\n\n## Active Tasks\n{task_block}\n"

        manifest_path.write_text(serialize_project_manifest(metadata, body), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to sync tasks to manifest file for {project_id}: {e}")
    finally:
        if close_db:
            db.close()


def sync_notes_to_manifest_file(project_id: str, db=None) -> None:
    """Rewrite the notes and attachment sections in PROJECT.md to match database notes."""
    close_db = False
    if db is None:
        db = cdb.SessionLocal()
        close_db = True
    try:
        project = db.query(Project).filter((Project.id == project_id) | (Project.slug == project_id)).first()
        if not project or not project.manifest_path:
            return
        manifest_path = Path(project.manifest_path)
        if not manifest_path.exists():
            return
        raw_text = manifest_path.read_text(encoding="utf-8")
        metadata, body = parse_project_manifest(raw_text)

        from core.database import Note
        notes = (
            db.query(Note)
            .filter(Note.project_id == project.id, Note.archived == False)
            .order_by(Note.pinned.desc(), Note.sort_order.asc(), Note.updated_at.desc())
            .all()
        )

        note_blocks = []
        for n in notes:
            if n.note_type == "checklist" and n.items:
                try:
                    items = json.loads(n.items) if isinstance(n.items, str) else n.items
                    lines = [f"### {n.title or 'Checklist'}"]
                    for it in items:
                        mk = "x" if (it.get("done") or it.get("checked")) else " "
                        lines.append(f"- [{mk}] {it.get('text', '')}")
                    note_blocks.append("\n".join(lines))
                except Exception:
                    pass
            elif n.content:
                title_line = f"### {n.title}\n" if n.title else ""
                note_blocks.append(f"{title_line}{n.content}")

        notes_section = "\n\n".join(note_blocks)
        if re.search(r"^## Project Notes.*?(?=^## |\Z)", body, flags=re.MULTILINE | re.DOTALL):
            body = re.sub(
                r"^## Project Notes.*?(?=^## |\Z)",
                f"## Project Notes\n{notes_section}\n\n" if notes_section else "",
                body,
                flags=re.MULTILINE | re.DOTALL,
            )
        elif notes_section:
            body = f"{body.strip()}\n\n## Project Notes\n{notes_section}\n"

        manifest_path.write_text(serialize_project_manifest(metadata, body), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to sync notes to manifest for {project_id}: {e}")
    finally:
        if close_db:
            db.close()


# ---------------------------------------------------------------------------
# Cross-Module Link Resolution
# ---------------------------------------------------------------------------

def resolve_project_links(project_id: str, db=None) -> List[Dict[str, Any]]:
    """Resolve cross-module pointers into human-readable rich snapshots."""
    close_db = False
    if db is None:
        db = cdb.SessionLocal()
        close_db = True

    try:
        links = db.query(ProjectLink).filter(ProjectLink.project_id == project_id).all()
        resolved = []

        for link in links:
            item = {
                "id": link.id,
                "target_type": link.target_type,
                "target_id": link.target_id,
                "label": link.label or link.target_id,
                "metadata": link.metadata_json or {},
                "status": "active",
                "details": None,
            }

            if link.target_type == "operations":
                notes_count = db.query(OperationsNote).filter(OperationsNote.key == link.target_id).count()
                item["details"] = {
                    "key": link.target_id,
                    "notes_count": notes_count,
                    "source": link.target_id.split(":")[0] if ":" in link.target_id else "worklist",
                }

            elif link.target_type == "document":
                doc = db.query(Document).filter(Document.id == link.target_id).first()
                if doc:
                    item["label"] = doc.title
                    item["details"] = {
                        "title": doc.title,
                        "language": doc.language,
                        "versions": doc.version_count,
                        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
                    }

            elif link.target_type == "calendar":
                event = db.query(CalendarEvent).filter(CalendarEvent.uid == link.target_id).first()
                if event:
                    item["label"] = event.summary
                    item["details"] = {
                        "summary": event.summary,
                        "dtstart": event.dtstart.isoformat() if event.dtstart else None,
                        "location": event.location,
                        "importance": event.importance,
                    }

            elif link.target_type == "email":
                item["details"] = {
                    "account_id": item["metadata"].get("account_id"),
                    "folder": item["metadata"].get("folder", "INBOX"),
                    "uid": item["metadata"].get("uid", link.target_id),
                    "subject": item["metadata"].get("subject", link.label),
                }

            resolved.append(item)

        return resolved
    finally:
        if close_db:
            db.close()


def project_to_dict(
    project: Project,
    db=None,
    include_tasks: bool = True,
    include_links: bool = True,
    include_content: bool = False,
    include_pinned_notes: bool = False,
) -> Dict[str, Any]:
    """Serialize a Project SQLAlchemy row into a structured dictionary."""
    content = ""
    if include_content and project.manifest_path and Path(project.manifest_path).exists():
        try:
            content = Path(project.manifest_path).read_text(encoding="utf-8")
        except Exception:
            content = ""

    data = {
        "id": project.id,
        "slug": project.slug,
        "name": project.name,
        "description": project.description,
        "agent_summary": getattr(project, "agent_summary", None),
        "status": project.status,
        "status_reason": getattr(project, "status_reason", None),
        "priority": project.priority,
        "owner": project.owner,
        "folder_path": project.folder_path,
        "manifest_path": project.manifest_path,
        "task_total": project.task_total or 0,
        "task_completed": project.task_completed or 0,
        "progress": round((project.task_completed / project.task_total * 100) if project.task_total else 0, 1),
        "agent_session_id": project.agent_session_id,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }

    if include_content:
        data["content"] = content


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

    if include_tasks:
        data["tasks"] = [
            {
                "id": t.id,
                "title": t.title,
                "completed": t.completed,
                "sort_order": t.sort_order,
                "due_date": t.due_date,
                "agent_session_id": t.agent_session_id,
            }
            for t in project.tasks
        ]

    if include_links:
        data["links"] = resolve_project_links(project.id, db=db)

    return data


def get_project_structure_and_spec(project_id: str, db=None) -> Dict[str, Any]:
    """Retrieve detailed workspace structure, key configs, git metadata, and spec files."""
    close_db = False
    if db is None:
        db = cdb.SessionLocal()
        close_db = True

    try:
        project = (
            db.query(Project)
            .filter((Project.id == project_id) | (Project.slug == project_id))
            .first()
        )
        if not project:
            return {}

        folder = Path(project.folder_path) if project.folder_path else None
        if not folder or not folder.exists():
            return {"error": "Folder not found"}

        IGNORES = {
            ".git", "node_modules", "venv", ".venv", "__pycache__", ".next",
            "dist", "build", ".dart_tool", ".gradle", "ios", "android", "data", "windows", "linux", "web"
        }

        # 1. Directory Tree & File Inventory
        tree = []
        key_files = []
        try:
            for entry in sorted(folder.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if entry.name in IGNORES:
                    continue
                is_dir = entry.is_dir()
                child_count = 0
                if is_dir:
                    try:
                        child_count = len([c for c in entry.iterdir() if c.name not in IGNORES])
                    except Exception:
                        pass
                item_info = {
                    "name": entry.name,
                    "is_dir": is_dir,
                    "size": entry.stat().st_size if not is_dir else 0,
                    "children": child_count if is_dir else 0,
                }
                tree.append(item_info)
                if not is_dir and entry.suffix.lower() in [".md", ".json", ".toml", ".yaml", ".yml", ".py", ".ts", ".js", ".xlsx", ".pdf", ".png", ".jpg"]:
                    key_files.append(entry.name)
        except Exception as e:
            logger.warning(f"Error scanning folder {folder}: {e}")

        # 2. Tech Stack & Configurations
        tech = {}
        pkg_json = folder / "package.json"
        if pkg_json.exists():
            try:
                pdata = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                tech["npm_package"] = pdata.get("name")
                tech["scripts"] = pdata.get("scripts", {})
                tech["dependencies"] = list(pdata.get("dependencies", {}).keys())
            except Exception:
                pass

        req_txt = folder / "requirements.txt"
        if req_txt.exists():
            try:
                tech["python_requirements"] = [
                    l.strip() for l in req_txt.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if l.strip() and not l.startswith("#")
                ][:15]
            except Exception:
                pass

        # 3. Spec File Content
        spec_content = ""
        spec_source = "PROJECT.md"
        spec_candidates = ["SPEC.md", "SPEC_Phase1.md", "SPECIFICATION.md", "README.md"]
        for cand in spec_candidates:
            cand_path = folder / cand
            if cand_path.exists():
                try:
                    spec_content = cand_path.read_text(encoding="utf-8", errors="ignore")
                    spec_source = cand
                    break
                except Exception:
                    pass

        if not spec_content and project.manifest_path and Path(project.manifest_path).exists():
            try:
                spec_content = Path(project.manifest_path).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass

        # 4. Sections Parsing from PROJECT.md
        sections = {"overview": "", "extended": "", "structure": "", "spec": spec_content}
        if project.manifest_path and Path(project.manifest_path).exists():
            try:
                m_raw = Path(project.manifest_path).read_text(encoding="utf-8", errors="ignore")
                meta, body = parse_project_manifest(m_raw)
                
                parts = re.split(r'(?m)^##\s+', body)
                sections["overview"] = parts[0].strip() if len(parts) > 0 else body
                
                for part in parts[1:]:
                    lines = part.splitlines()
                    header = lines[0].strip().lower()
                    content_block = "\n".join(lines[1:]).strip()
                    if any(k in header for k in ["architecture", "tech stack", "components", "background"]):
                        sections["extended"] += f"## {lines[0]}\n\n{content_block}\n\n"
                    elif any(k in header for k in ["objective", "goal", "task", "milestone"]):
                        sections["overview"] += f"\n\n## {lines[0]}\n\n{content_block}\n\n"
                    elif any(k in header for k in ["structure", "topology", "schema", "flow", "execution"]):
                        sections["structure"] += f"## {lines[0]}\n\n{content_block}\n\n"
            except Exception as e:
                logger.warning(f"Error parsing sections: {e}")

        return {
            "project_id": project.id,
            "slug": project.slug,
            "folder_path": str(folder),
            "tree": tree,
            "key_files": key_files,
            "tech": tech,
            "spec_source": spec_source,
            "spec_content": spec_content,
            "sections": sections,
        }
    finally:
        if close_db:
            db.close()


def append_project_execution_log(
    project_id: str,
    action: str,
    details: str,
    status: str = "completed",
    model: Optional[str] = None,
    db=None,
) -> None:
    """Append a structured, sequential execution entry into PROJECT.md and the project logs/ directory."""
    close_db = False
    if db is None:
        db = cdb.SessionLocal()
        close_db = True
    try:
        project = db.query(Project).filter((Project.id == project_id) | (Project.slug == project_id)).first()
        if not project or not project.folder_path:
            return

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        model_str = f" via `{model}`" if model else ""
        status_str = f"[{status.upper()}]"
        clean_details = " ".join(details.splitlines()).strip()
        if len(clean_details) > 200:
            clean_details = clean_details[:197] + "..."
        entry_line = f"- *{now_iso}* {status_str} **{action}**{model_str}: {clean_details}"

        # 1. Append to PROJECT.md ## Execution Log section
        if project.manifest_path and Path(project.manifest_path).exists():
            try:
                manifest_path = Path(project.manifest_path)
                raw_text = manifest_path.read_text(encoding="utf-8")
                metadata, body = parse_project_manifest(raw_text)

                if re.search(r"^## Execution Log.*?(?=^## |\Z)", body, flags=re.MULTILINE | re.DOTALL):
                    body = re.sub(
                        r"^(## Execution Log\s*\n)",
                        r"\1" + entry_line.replace("\\", "\\\\") + "\n",
                        body,
                        flags=re.MULTILINE,
                    )
                else:
                    body = f"{body.strip()}\n\n## Execution Log\n{entry_line}\n"

                manifest_path.write_text(serialize_project_manifest(metadata, body), encoding="utf-8")
            except Exception as me:
                logger.warning(f"Failed to append execution log to PROJECT.md for {project_id}: {me}")

        # 2. Append to logs/execution.log
        try:
            logs_dir = Path(project.folder_path) / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_file = logs_dir / "execution.log"
            with log_file.open("a", encoding="utf-8") as f:
                f.write(f"[{now_iso}] status={status} action={action} model={model or 'none'} details={details}\n")
        except Exception as le:
            logger.warning(f"Failed to write to logs/execution.log for {project_id}: {le}")
    except Exception as e:
        logger.warning(f"Failed to record execution log for project {project_id}: {e}")
    finally:
        if close_db:
            db.close()


