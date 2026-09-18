"""Exercise deployment refusal and data recovery in disposable directories."""
import subprocess

import pytest

from scripts.deploy_revision import deploy_revision, git
from scripts.reconcile_phone_data import reconcile, rollback


def test_copy_repeat_and_rollback_preserve_later_data(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "record.json").write_text('{"approved":false}')
    (source / "attachment.txt").write_text("original")
    manifest = tmp_path / "manifest.json"
    report = reconcile(source, destination, manifest, apply=True)
    assert len(report["created"]) == 2
    assert reconcile(source, destination, tmp_path / "next.json")["missing"] == []
    (destination / "record.json").write_text('{"approved":true}')
    (destination / "later.txt").write_text("new user data")
    result = rollback(manifest)
    assert result["preserved"] == ["record.json"]
    assert (destination / "later.txt").read_text() == "new user data"
    assert (source / "attachment.txt").exists()


def test_conflict_refuses_all_writes(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir(); destination.mkdir()
    (source / "a.txt").write_text("new")
    (source / "b.txt").write_text("source")
    (destination / "b.txt").write_text("existing")
    with pytest.raises(ValueError, match="conflicts"):
        reconcile(source, destination, tmp_path / "manifest.json", apply=True)
    assert not (destination / "a.txt").exists()
    assert (destination / "b.txt").read_text() == "existing"


def test_deployment_requires_clean_expected_branch_and_preserves_untracked(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "daily-driver")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "tracked").write_text("one")
    git(repo, "add", "tracked"); git(repo, "commit", "-m", "first")
    first = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-c", "repair")
    (repo / "tracked").write_text("two")
    git(repo, "commit", "-am", "second")
    second = git(repo, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="branch"):
        deploy_revision(repo, second, apply=True)
    git(repo, "switch", "daily-driver")
    (repo / "tracked").write_text("dirty")
    with pytest.raises(ValueError, match="local changes"):
        deploy_revision(repo, second, apply=True)
    (repo / "tracked").write_text("one")
    (repo / "untracked").write_text("keep")
    assert deploy_revision(repo, second)["previous"] == first
    assert git(repo, "rev-parse", "HEAD") == first
    deploy_revision(repo, second, apply=True)
    assert git(repo, "rev-parse", "HEAD") == second
    assert (repo / "untracked").read_text() == "keep"
    with pytest.raises(subprocess.CalledProcessError):
        deploy_revision(repo, first, apply=True)
