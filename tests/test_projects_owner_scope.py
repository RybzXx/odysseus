"""Exercise ownership at both public entry points without production data."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core import database as db
from routes.projects import projects_routes
from src.agent_tools.project_tools import ManageProjectsTool
from src.projects_manager import save_project_content_to_disk


@pytest.fixture
def projects(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(db, "SessionLocal", sessions)
    monkeypatch.setattr(projects_routes, "get_current_user", lambda request: "bob")
    with sessions() as session:
        for key, owner in [("private", "alice"), ("mine", "bob"), ("shared", None)]:
            folder = tmp_path / key
            folder.mkdir()
            (folder / "PROJECT.md").write_text("# Original\n", encoding="utf-8")
            session.add(db.Project(id=key, slug=key, name=key, owner=owner,
                folder_path=str(folder), manifest_path=str(folder / "PROJECT.md")))
        session.add(db.ProjectTask(id="private-task", project_id="private", title="private"))
        session.add(db.ProjectTask(id="mine-task", project_id="mine", title="mine"))
        session.add(db.Document(id="secret", title="Secret title", owner="alice"))
        session.add(db.ProjectLink(id="secret-link", project_id="shared", target_type="document",
            target_id="secret", label="Secret label", metadata_json={"private": "hidden"}))
        session.commit()
    app = FastAPI()
    app.include_router(projects_routes.setup_projects_routes())
    with TestClient(app) as client:
        yield client, sessions, tmp_path
    engine.dispose()


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/private", None), ("GET", "/private/structure", None),
    ("PUT", "/private", {"name": "changed"}), ("DELETE", "/private", None),
    ("POST", "/private/sync", {}), ("POST", "/private/summarize", {}),
    ("POST", "/private/agent_session", {}),
    ("POST", "/private/tasks", {"title": "changed"}),
    ("PATCH", "/private/tasks/private-task", {"completed": True}),
    ("DELETE", "/private/tasks/private-task", None),
    ("PATCH", "/shared/tasks/mine-task", {"completed": True}),
    ("DELETE", "/shared/tasks/mine-task", None),
    ("POST", "/shared/agent_session", {"task_id": "mine-task"}),
    ("DELETE", "/mine/links/secret-link", None),
])
def test_routes_reject_inaccessible_or_mismatched_objects(projects, method, path, body):
    client, sessions, folder = projects
    response = client.request(method, "/api/projects" + path, json=body)
    assert response.status_code == 404, response.text
    with sessions() as session:
        assert session.get(db.Project, "private").name == "private"
        assert not session.get(db.ProjectTask, "mine-task").completed
        assert session.query(db.Session).count() == 0
    assert (folder / "private/PROJECT.md").read_text() == "# Original\n"


def test_shared_project_does_not_disclose_private_link(projects):
    client, _, _ = projects
    response = client.get("/api/projects/shared")
    assert response.status_code == 200
    assert response.json()["project"]["links"] == []
    assert {p["id"] for p in client.get("/api/projects").json()["projects"]} == {"mine", "shared"}


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["get", "get_context", "update", "add_task", "link_item", "toggle_task"])
async def test_tool_cannot_access_another_owner(projects, action):
    result = await ManageProjectsTool().execute(json.dumps({
        "action": action, "project_id": "private", "task_id": "private-task",
        "name": "changed", "task_title": "changed", "link_type": "document", "link_target": "secret",
    }), owner="bob")
    assert result["exit_code"] == 1


def test_disk_write_checks_owner_before_opening_manifest(projects):
    _, _, folder = projects
    with pytest.raises(FileNotFoundError):
        save_project_content_to_disk("private", "overwritten", owner="bob")
    assert (folder / "private/PROJECT.md").read_text() == "# Original\n"


@pytest.mark.asyncio
async def test_missing_identity_is_not_admin(projects):
    result = await ManageProjectsTool().execute('{"action":"list"}')
    assert [p["id"] for p in result["projects"]] == ["shared"]


@pytest.mark.asyncio
async def test_repeated_completion_does_not_inflate_count(projects):
    _, sessions, _ = projects
    tool = ManageProjectsTool()
    for _ in range(2):
        result = await tool.execute('{"action":"complete_task","task_id":"mine-task","completed":true}', owner="bob")
        assert result["exit_code"] == 0
    with sessions() as session:
        assert session.get(db.Project, "mine").task_completed == 1
