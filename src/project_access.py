"""Project access rules shared by HTTP routes, tools, and disk operations."""

from sqlalchemy import or_

from core.database import Project


def project_scope(owner):
    """Allow shared projects and the caller's projects. Missing identity is not admin."""
    shared = Project.owner.is_(None)
    return or_(shared, Project.owner == owner) if owner else shared


def find_project(db, project_id, owner):
    """Return an accessible project by ID or slug, or None without disclosing it."""
    return db.query(Project).filter(
        project_scope(owner),
        or_(Project.id == project_id, Project.slug == project_id),
    ).first()


def require_project(db, project_id, owner):
    """Raise before any disk or database mutation when access is denied."""
    project = find_project(db, project_id, owner)
    if project is None:
        raise FileNotFoundError("Project not found")
    return project
