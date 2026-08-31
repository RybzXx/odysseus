"""tests/test_companion_todos.py

Unit and integration tests for the unified companion todos gateway.
Tests note checklist items, project tasks, bi-directional toggles, and creation.
"""

import json
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, Note, Project, ProjectTask
from companion.todos import fetch_all_todos, toggle_todo, create_todo


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_fetch_todos_empty(db_session):
    items = fetch_all_todos(db_session, owner="alice")
    assert items == []


def test_fetch_todos_notes_and_projects(db_session):
    note = Note(
        id="note_1",
        owner="alice",
        title="Groceries",
        note_type="checklist",
        items=json.dumps([
            {"id": "item_a", "text": "Milk", "done": False},
            {"id": "item_b", "text": "Eggs", "done": True},
        ]),
        archived=False,
    )
    db_session.add(note)

    proj = Project(
        id="proj_1",
        slug="odysseus-mobile",
        owner="alice",
        name="Odysseus Mobile",
        status="active",
        folder_path="workspaces/odysseus-mobile",
        manifest_path="workspaces/odysseus-mobile/PROJECT.md",
        task_total=2,
        task_completed=0,
    )
    db_session.add(proj)

    task1 = ProjectTask(
        id="ptask_1",
        project_id="proj_1",
        title="Write tests",
        completed=False,
        sort_order=0,
    )
    task2 = ProjectTask(
        id="ptask_2",
        project_id="proj_1",
        title="Deploy widget",
        completed=True,
        sort_order=1,
    )
    db_session.add_all([task1, task2])
    db_session.commit()

    # Active only
    active_items = fetch_all_todos(db_session, owner="alice", include_completed=False)
    assert len(active_items) == 2
    titles = [it["title"] for it in active_items]
    assert "Milk" in titles
    assert "Write tests" in titles

    # Include completed
    all_items = fetch_all_todos(db_session, owner="alice", include_completed=True)
    assert len(all_items) == 4


def test_toggle_note_todo(db_session):
    note = Note(
        id="note_1",
        owner="alice",
        title="Tasks",
        items=json.dumps([{"id": "item_1", "text": "Buy coffee", "done": False}]),
        archived=False,
    )
    db_session.add(note)
    db_session.commit()

    res = toggle_todo(db_session, owner="alice", item_id="note:note_1:item_1")
    assert res["ok"] is True
    assert res["completed"] is True

    db_session.refresh(note)
    items = json.loads(note.items)
    assert items[0]["done"] is True

    # Toggle back to false
    res2 = toggle_todo(db_session, owner="alice", item_id="note:note_1:item_1")
    assert res2["completed"] is False


def test_toggle_project_todo(db_session):
    proj = Project(
        id="proj_1",
        slug="odysseus",
        owner="alice",
        name="Odysseus",
        folder_path="workspaces/odysseus",
        manifest_path="workspaces/odysseus/PROJECT.md",
        task_total=1,
        task_completed=0,
    )
    db_session.add(proj)
    task = ProjectTask(id="ptask_1", project_id="proj_1", title="Build APK", completed=False)
    db_session.add(task)
    db_session.commit()

    res = toggle_todo(db_session, owner="alice", item_id="project:proj_1:ptask_1")
    assert res["ok"] is True
    assert res["completed"] is True

    db_session.refresh(task)
    assert task.completed is True
    db_session.refresh(proj)
    assert proj.task_completed == 1


def test_create_todo_note_and_project(db_session):
    res1 = create_todo(db_session, owner="alice", title="New note item", target_type="note")
    assert res1["ok"] is True
    assert res1["item"]["title"] == "New note item"
    assert res1["item"]["source_type"] == "note"

    proj = Project(
        id="proj_1",
        slug="main-project",
        owner="alice",
        name="Main Project",
        folder_path="workspaces/main-project",
        manifest_path="workspaces/main-project/PROJECT.md",
    )
    db_session.add(proj)
    db_session.commit()

    res2 = create_todo(db_session, owner="alice", title="New project task", target_type="project", target_id="proj_1")
    assert res2["ok"] is True
    assert res2["item"]["title"] == "New project task"
    assert res2["item"]["source_type"] == "project"
