"""Regression test for the project.task_completed double-count race.

Two concurrent requests toggling the same task to the same `completed` value
each load the task into their own session's identity map before either
commits. The old code read task.completed from that (stale) in-memory copy
to decide whether to bump the counter, so both requests could see "not yet
completed" and both increment -- double-counting one task. The fix
recomputes the counter from a COUNT query instead, which always hits the
database directly rather than the identity map.
"""

import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as db
import companion.todos as todos


@pytest.fixture
def two_sessions():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}")
    db.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    setup = Session()
    setup.add(db.Project(
        id="proj1", slug="p1", name="P1", status="active",
        folder_path="x", manifest_path="x/PROJECT.md",
        task_total=1, task_completed=0,
    ))
    setup.add(db.ProjectTask(id="ptask1", project_id="proj1", title="T1", completed=False))
    setup.commit()
    setup.close()

    session_a = Session()
    session_b = Session()
    try:
        yield Session, session_a, session_b
    finally:
        session_a.close()
        session_b.close()
        engine.dispose()  # release the file handle before removing it (Windows locks open files)
        os.remove(path)


def test_concurrent_identical_toggle_does_not_double_count(two_sessions):
    Session, session_a, session_b = two_sessions

    # Both sessions load the task while the DB still shows completed=False --
    # this is the actual race precondition, independent of real thread timing.
    # References MUST be held: SQLAlchemy's default identity map is weak, so
    # an unbound query result can be garbage-collected before toggle_todo's
    # own query runs, silently turning this into a fresh (non-stale) read and
    # making the race impossible to reproduce.
    task_a = session_a.query(db.ProjectTask).filter_by(id="ptask1").first()
    task_b = session_b.query(db.ProjectTask).filter_by(id="ptask1").first()
    assert task_a is not None and task_b is not None

    todos.toggle_todo(session_a, owner=None, item_id="project:proj1:ptask1", completed=True)
    # session_b's identity map still holds completed=False for this task,
    # exactly as it would if this were a second, concurrent request.
    todos.toggle_todo(session_b, owner=None, item_id="project:proj1:ptask1", completed=True)

    checker = Session()
    project = checker.query(db.Project).filter_by(id="proj1").first()
    task = checker.query(db.ProjectTask).filter_by(id="ptask1").first()
    checker.close()

    assert task.completed is True
    assert project.task_completed == 1, (
        f"expected 1 (one task, toggled twice to the same value), got {project.task_completed}"
    )
