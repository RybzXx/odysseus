"""Validate and fast-forward a clean checkout to one exact commit."""
import argparse
import json
from pathlib import Path
import subprocess


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, capture_output=True)
    return result.stdout.strip()


def deploy_revision(repo, commit, *, branch="daily-driver", apply=False):
    """Keep untracked files and refuse branch drift, tracked edits, or history rewrites."""
    repo = Path(repo).resolve(strict=True)
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("An exact lowercase 40-character commit ID is required")
    if git(repo, "branch", "--show-current") != branch:
        raise ValueError("Checkout is not on the expected branch")
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Tracked files have local changes")
    desired = git(repo, "rev-parse", "--verify", commit + "^{commit}")
    previous = git(repo, "rev-parse", "HEAD")
    git(repo, "merge-base", "--is-ancestor", previous, desired)
    if apply:
        git(repo, "merge", "--ff-only", desired)
        if git(repo, "rev-parse", "HEAD") != desired:
            raise RuntimeError("Deployed commit does not match the requested commit")
    return {"previous": previous, "desired": desired, "branch": branch, "applied": apply}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--branch", default="daily-driver")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(deploy_revision(args.repo, args.commit, branch=args.branch, apply=args.apply)))
