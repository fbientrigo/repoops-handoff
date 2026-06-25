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
