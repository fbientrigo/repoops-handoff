from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def require_git() -> None:
    if shutil.which("git") is None:
        pytest.skip("git is required for this test")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    require_git()
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def clean_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "RepoOps Test")
    (repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial commit")
    return repo


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare", "-b", "main")
    return remote


def clone_repo(dest: Path, bare_remote: Path) -> Path:
    require_git()
    subprocess.run(
        ["git", "clone", str(bare_remote), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(dest, "config", "user.email", "test@example.com")
    git(dest, "config", "user.name", "RepoOps Test")
    return dest


@pytest.fixture
def repo_with_upstream(tmp_path: Path, bare_remote: Path) -> Path:
    clone = clone_repo(tmp_path / "clone", bare_remote)
    # Force the branch name explicitly: cloning an empty bare repo has
    # version-dependent default-branch inference, and we need a known name.
    git(clone, "checkout", "-B", "main")
    (clone / "README.md").write_text("# test repo\n", encoding="utf-8")
    git(clone, "add", "README.md")
    git(clone, "commit", "-m", "initial commit")
    git(clone, "push", "-u", "origin", "HEAD:main")
    return clone
