from pathlib import Path

from repoops.config import RepoConfig
from repoops.git_scan import (
    PorcelainSummary,
    classify_risk_flags,
    parse_porcelain_status,
    redact_secret_like_path,
    scan_repo,
)


def test_scan_missing_repo(tmp_path: Path) -> None:
    repo = RepoConfig(name="missing", path=tmp_path / "does-not-exist")

    snapshot = scan_repo(repo)

    assert snapshot.exists is False
    assert snapshot.is_git_repo is False
    assert snapshot.dirty is False
    assert "repo_missing" in snapshot.risk_flags


def test_scan_non_git_directory(tmp_path: Path) -> None:
    non_git = tmp_path / "plain-dir"
    non_git.mkdir()
    repo = RepoConfig(name="plain", path=non_git)

    snapshot = scan_repo(repo)

    assert snapshot.exists is True
    assert snapshot.is_git_repo is False
    assert snapshot.branch is None
    assert snapshot.head is None
    assert "not_git_repo" in snapshot.risk_flags


def test_scan_clean_git_repo(clean_git_repo: Path) -> None:
    repo = RepoConfig(name="clean", path=clean_git_repo)

    snapshot = scan_repo(repo)

    assert snapshot.exists is True
    assert snapshot.is_git_repo is True
    assert snapshot.dirty is False
    assert snapshot.counts.modified == 0
    assert snapshot.counts.staged == 0
    assert snapshot.counts.untracked == 0
    assert snapshot.branch
    assert snapshot.head
    assert "dirty" not in snapshot.risk_flags


def test_scan_dirty_git_repo_modified_and_untracked(clean_git_repo: Path) -> None:
    (clean_git_repo / "README.md").write_text("# changed\n", encoding="utf-8")
    (clean_git_repo / "notes.md").write_text("todo\n", encoding="utf-8")
    repo = RepoConfig(name="dirty", path=clean_git_repo)

    snapshot = scan_repo(repo)

    assert snapshot.dirty is True
    assert snapshot.counts.modified == 1
    assert snapshot.counts.untracked == 1
    assert "dirty" in snapshot.risk_flags
    assert "untracked_files" in snapshot.risk_flags


def test_parse_porcelain_status_counts() -> None:
    output = """ M src/model.py
M  README.md
?? notes/todo.md
 D old/file.py
R  old.py -> new.py
UU conflict.py
"""

    summary = parse_porcelain_status(output)

    assert summary.counts.modified == 2
    assert summary.counts.staged == 2
    assert summary.counts.untracked == 1
    assert summary.counts.deleted == 1
    assert summary.counts.renamed == 1
    assert summary.counts.conflicted == 1


def test_notable_files_respects_max_files(clean_git_repo: Path) -> None:
    for index in range(15):
        (clean_git_repo / f"file_{index}.txt").write_text("x\n", encoding="utf-8")
    repo = RepoConfig(name="many", path=clean_git_repo)

    snapshot = scan_repo(repo, max_files_per_repo=5)

    assert len(snapshot.notable_files) == 5


def test_untracked_can_be_excluded_from_notable_files(clean_git_repo: Path) -> None:
    (clean_git_repo / "untracked.txt").write_text("x\n", encoding="utf-8")
    repo = RepoConfig(name="repo", path=clean_git_repo)

    snapshot = scan_repo(repo, include_untracked=False)

    assert snapshot.counts.untracked == 1
    assert "untracked.txt" not in snapshot.notable_files


def test_risk_flags_many_changes() -> None:
    summary = PorcelainSummary()
    for index in range(21):
        summary.entries.append(
            parse_porcelain_status(f" M file_{index}.py\n").entries[0]
        )

    flags = classify_risk_flags(
        exists=True,
        is_git_repo=True,
        branch="main",
        summary=summary,
        many_changes_threshold=20,
    )

    assert "many_changes" in flags


def test_risk_flags_possible_secret_file_redacted() -> None:
    summary = parse_porcelain_status("?? .env\n M config/prod.credentials.json\n")

    flags = classify_risk_flags(
        exists=True,
        is_git_repo=True,
        branch="main",
        summary=summary,
    )

    assert "possible_secret_file" in flags
    assert redact_secret_like_path(".env") == "[REDACTED_SECRET_PATH]"
    assert redact_secret_like_path("config/prod.credentials.json") == "config/[REDACTED_SECRET_PATH]"


def test_risk_flags_dependency_file_changed() -> None:
    summary = parse_porcelain_status(" M pyproject.toml\n M requirements.txt\n M pixi.lock\n")

    flags = classify_risk_flags(
        exists=True,
        is_git_repo=True,
        branch="main",
        summary=summary,
    )

    assert "dependency_file_changed" in flags


def test_risk_flags_ci_file_changed() -> None:
    summary = parse_porcelain_status(" M .github/workflows/ci.yml\n")

    flags = classify_risk_flags(
        exists=True,
        is_git_repo=True,
        branch="main",
        summary=summary,
    )

    assert "ci_file_changed" in flags


def test_risk_flags_notebook_changed() -> None:
    summary = parse_porcelain_status(" M analysis/demo.ipynb\n")

    flags = classify_risk_flags(
        exists=True,
        is_git_repo=True,
        branch="main",
        summary=summary,
    )

    assert "notebook_changed" in flags


def test_risk_flags_detached_head() -> None:
    flags = classify_risk_flags(
        exists=True,
        is_git_repo=True,
        branch="HEAD",
        summary=PorcelainSummary(),
    )

    assert "detached_head" in flags
