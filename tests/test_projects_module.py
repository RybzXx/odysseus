"""tests/test_projects_module.py

Comprehensive test suite for the Hybrid Projects Module in Odysseus.
Tests:
- Filesystem scaffolding and PROJECT.md frontmatter parsing/serialization
- Bidirectional disk-to-database synchronization
- Tasks checklist parsing and toggling
- Cross-module link creation and resolution (Operations, Email, Calendar, Document)
- ManageProjectsTool agent actions (list, get, create, update, add_task, toggle_task, link_item, get_context)
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from core.database import Base, SessionLocal, engine, Project, ProjectTask, ProjectLink, Document
from src.projects_manager import (
    create_project,
    parse_project_manifest,
    serialize_project_manifest,
    parse_tasks_from_markdown,
    sync_project_disk_and_db,
    save_project_content_to_disk,
    resolve_project_links,
    project_to_dict,
)
from src.agent_tools.project_tools import ManageProjectsTool


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Create isolated SQLite tables for tests and temporary project directory."""
    temp_dir = tempfile.mkdtemp(prefix="odysseus_test_projects_")
    monkeypatch.setattr("src.projects_manager.DEFAULT_PROJECTS_DIR", Path(temp_dir))
    
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import core.database as cdb
    
    db_file = Path(temp_dir) / "test_app.db"
    test_engine = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})
    test_session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    monkeypatch.setattr(cdb, "engine", test_engine)
    monkeypatch.setattr(cdb, "SessionLocal", test_session)

    # Ensure tables exist
    cdb.Base.metadata.create_all(bind=test_engine)

    yield

    # Cleanup temp directory
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_frontmatter_parser_and_serializer():
    """Verify YAML frontmatter extraction and serialization."""
    raw_md = """---
id: proj_test_01
name: "Alpha Test Project"
slug: alpha-test
status: active
priority: high
links:
  - type: operations
    key: "bookings:1042"
---

# Alpha Test Project
Project summary and details.

## Active Tasks
- [ ] First setup task
- [x] Completed task
"""
    meta, body = parse_project_manifest(raw_md)
    assert meta.get("id") == "proj_test_01"
    assert meta.get("name") == "Alpha Test Project"
    assert meta.get("status") == "active"
    assert meta.get("priority") == "high"
    assert len(meta.get("links", [])) == 1

    tasks = parse_tasks_from_markdown(body)
    assert len(tasks) == 2
    assert tasks[0]["title"] == "First setup task"
    assert tasks[0]["completed"] is False
    assert tasks[1]["title"] == "Completed task"
    assert tasks[1]["completed"] is True

    # Roundtrip serialization
    serialized = serialize_project_manifest(meta, body)
    meta2, body2 = parse_project_manifest(serialized)
    assert meta2.get("id") == meta.get("id")
    assert meta2.get("name") == meta.get("name")


def test_create_and_sync_project():
    """Test project workspace creation, scaffolding, and disk-to-DB sync."""
    res = create_project(
        name="Bil Weekend Dispatch",
        description="Testing operational dispatch coordination.",
        priority="high",
        owner="test_admin",
    )

    assert res["id"].startswith("proj_")
    assert res["slug"].startswith("bil-weekend-dispatch")
    assert res["task_total"] >= 2
    assert res["task_completed"] == 0

    manifest_file = Path(res["manifest_path"])
    assert manifest_file.exists()
    assert (manifest_file.parent / "docs").is_dir()
    assert (manifest_file.parent / "tasks").is_dir()
    assert (manifest_file.parent / "logs").is_dir()

    # Simulate manual edit to PROJECT.md on disk (e.g. human checking off a task in Obsidian)
    disk_content = manifest_file.read_text(encoding="utf-8")
    updated_content = disk_content.replace("- [ ] Initial project setup", "- [x] Initial project setup")
    manifest_file.write_text(updated_content, encoding="utf-8")

    # Trigger sync
    synced = sync_project_disk_and_db(res["id"], owner="test_admin")
    assert synced["task_completed"] == 1
    assert synced["tasks"][0]["completed"] is True


def test_cross_module_links_resolution():
    """Test attaching and resolving cross-module links (Operations, Document)."""
    import core.database as cdb
    db = cdb.SessionLocal()
    try:
        # Create dummy Document
        doc = Document(
            id="doc_pricing_rules_01",
            title="Standard Pricing Rules",
            language="markdown",
            current_content="# Pricing\nRules here.",
            version_count=1,
        )
        db.add(doc)
        db.commit()
    finally:
        db.close()

    proj = create_project(
        name="Logistics Pipeline",
        links=[
            {"type": "operations", "key": "bookings:8819", "label": "Booking 8819"},
            {"type": "document", "id": "doc_pricing_rules_01"},
        ],
    )

    assert len(proj["links"]) == 2
    ops_link = next(l for l in proj["links"] if l["target_type"] == "operations")
    assert ops_link["target_id"] == "bookings:8819"

    doc_link = next(l for l in proj["links"] if l["target_type"] == "document")
    assert doc_link["target_id"] == "doc_pricing_rules_01"
    assert doc_link["label"] == "Standard Pricing Rules"


def test_manage_projects_agent_tool():
    """Test AI agent interactions via ManageProjectsTool."""
    import asyncio
    import json

    async def _run():
        tool = ManageProjectsTool()

        # 1. Create project
        create_args = {
            "action": "create",
            "name": "Autonomous Agent Workspace",
            "description": "Agent coordination test.",
            "priority": "critical",
        }
        res = await tool.execute(json.dumps(create_args))
        assert res["exit_code"] == 0
        proj_id = res["project"]["id"]

        # 2. Add task via tool
        add_task_args = {
            "action": "add_task",
            "project_id": proj_id,
            "task_title": "Run security audit on email gate",
        }
        res_task = await tool.execute(json.dumps(add_task_args))
        assert res_task["exit_code"] == 0
        task_id = res_task["task"]["id"]

        # 3. Toggle task via tool
        toggle_args = {
            "action": "toggle_task",
            "task_id": task_id,
            "completed": True,
        }
        res_toggle = await tool.execute(json.dumps(toggle_args))
        assert res_toggle["exit_code"] == 0
        assert res_toggle["task"]["completed"] is True

        # 4. Link item via tool
        link_args = {
            "action": "link_item",
            "project_id": proj_id,
            "link_type": "operations",
            "link_target": "queue_requests:99",
            "link_label": "High Priority Queue Item",
        }
        res_link = await tool.execute(json.dumps(link_args))
        assert res_link["exit_code"] == 0

        # 5. Get context for agent reasoning
        ctx_args = {
            "action": "get_context",
            "project_id": proj_id,
        }
        res_ctx = await tool.execute(json.dumps(ctx_args))
        assert res_ctx["exit_code"] == 0
        assert "Autonomous Agent Workspace" in res_ctx["context_text"]
        assert "Run security audit on email gate" in res_ctx["context_text"]
        assert "High Priority Queue Item" in res_ctx["context_text"]

        # 6. List projects
        list_args = {"action": "list"}
        res_list = await tool.execute(json.dumps(list_args))
        assert res_list["exit_code"] == 0
        assert res_list["count"] >= 1

    asyncio.run(_run())


def test_projects_api_routes():
    """Test FastAPI REST endpoints for projects."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.projects.projects_routes import setup_projects_routes

    app = FastAPI()
    app.include_router(setup_projects_routes())
    client = TestClient(app)

    # 1. POST /api/projects
    create_res = client.post("/api/projects", json={
        "name": "Operations Hub Live",
        "description": "Live route test project",
        "priority": "high",
    })
    assert create_res.status_code == 200
    p = create_res.json()["project"]
    proj_id = p["id"]

    # 2. GET /api/projects
    list_res = client.get("/api/projects")
    assert list_res.status_code == 200
    assert len(list_res.json()["projects"]) >= 1

    # 3. GET /api/projects/{id}
    get_res = client.get(f"/api/projects/{proj_id}")
    assert get_res.status_code == 200
    assert get_res.json()["project"]["name"] == "Operations Hub Live"

    # 4. POST /api/projects/{id}/tasks
    task_res = client.post(f"/api/projects/{proj_id}/tasks", json={
        "title": "Check worklist queue",
        "completed": False,
    })
    assert task_res.status_code == 200
    task_id = task_res.json()["task"]["id"]

    # 5. PATCH /api/projects/{id}/tasks/{task_id}
    patch_res = client.patch(f"/api/projects/{proj_id}/tasks/{task_id}", json={
        "completed": True,
    })
    assert patch_res.status_code == 200
    assert patch_res.json()["task"]["completed"] is True

    # 6. POST /api/projects/{id}/links
    link_res = client.post(f"/api/projects/{proj_id}/links", json={
        "target_type": "operations",
        "target_id": "bookings:9999",
        "label": "Test Booking 9999",
    })
    assert link_res.status_code == 200
    assert link_res.json()["link"]["target_id"] == "bookings:9999"

    # 7. POST /api/projects/{id}/sync
    sync_res = client.post(f"/api/projects/{proj_id}/sync")
    assert sync_res.status_code == 200
    assert sync_res.json()["synced"] is True

    # 8. POST /api/projects/{id}/agent_session
    session_res = client.post(f"/api/projects/{proj_id}/agent_session")
    assert session_res.status_code == 200
    assert "session_id" in session_res.json()

