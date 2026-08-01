from pathlib import Path

import pytest

from conftest import clone_repo, git
from repoops.config import DefaultsConfig, MachineConfig, RepoConfig, RepoOpsConfig
from repoops.git_scan import (
    ChangeCounts,
    PorcelainSummary,
    RemoteSyncStatus,
    RepoSnapshot,
    _run_git,
    _sanitize_git_error,
    build_snapshot,
    classify_risk_flags,
    compute_attention_score,
    parse_porcelain_status,
    redact_secret_like_path,
    resolve_fetch,
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
        summary.entries.append(parse_porcelain_status(f" M file_{index}.py\n").entries[0])

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
    redacted = redact_secret_like_path("config/prod.credentials.json")
    assert redacted == "config/[REDACTED_SECRET_PATH]"


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


# --- Remote sync status -----------------------------------------------------


def test_scan_repo_no_upstream(clean_git_repo: Path) -> None:
    repo = RepoConfig(name="repo", path=clean_git_repo)

    snapshot = scan_repo(repo)

    assert snapshot.remote.has_upstream is False
    assert snapshot.remote.upstream is None
    assert snapshot.remote.ahead is None
    assert snapshot.remote.behind is None
    assert "no_upstream" in snapshot.risk_flags


def test_scan_repo_clean_with_upstream(repo_with_upstream: Path) -> None:
    repo = RepoConfig(name="repo", path=repo_with_upstream)

    snapshot = scan_repo(repo)

    assert snapshot.remote.has_upstream is True
    assert snapshot.remote.upstream == "origin/main"
    assert snapshot.remote.ahead == 0
    assert snapshot.remote.behind == 0
    assert "ahead_remote" not in snapshot.risk_flags
    assert "behind_remote" not in snapshot.risk_flags
    assert "diverged_remote" not in snapshot.risk_flags
    assert "no_upstream" not in snapshot.risk_flags


def test_scan_repo_ahead_of_upstream(repo_with_upstream: Path) -> None:
    (repo_with_upstream / "local.txt").write_text("local only\n", encoding="utf-8")
    git(repo_with_upstream, "add", "local.txt")
    git(repo_with_upstream, "commit", "-m", "local commit")
    repo = RepoConfig(name="repo", path=repo_with_upstream)

    snapshot = scan_repo(repo)

    assert snapshot.remote.ahead == 1
    assert snapshot.remote.behind == 0
    assert "ahead_remote" in snapshot.risk_flags
    assert "behind_remote" not in snapshot.risk_flags
    assert "diverged_remote" not in snapshot.risk_flags


def test_scan_repo_behind_upstream(
    tmp_path: Path, bare_remote: Path, repo_with_upstream: Path
) -> None:
    other_clone = clone_repo(tmp_path / "other", bare_remote)
    (other_clone / "from_other.txt").write_text("from other machine\n", encoding="utf-8")
    git(other_clone, "add", "from_other.txt")
    git(other_clone, "commit", "-m", "other commit")
    git(other_clone, "push", "origin", "HEAD:main")
    repo = RepoConfig(name="repo", path=repo_with_upstream)

    snapshot = scan_repo(repo, fetch=True, fetch_timeout_seconds=20)

    assert snapshot.remote.fetched is True
    assert snapshot.remote.ahead == 0
    assert snapshot.remote.behind == 1
    assert "behind_remote" in snapshot.risk_flags
    assert "ahead_remote" not in snapshot.risk_flags
    assert "diverged_remote" not in snapshot.risk_flags


def test_scan_repo_diverged_from_upstream(
    tmp_path: Path, bare_remote: Path, repo_with_upstream: Path
) -> None:
    other_clone = clone_repo(tmp_path / "other", bare_remote)
    (other_clone / "from_other.txt").write_text("from other machine\n", encoding="utf-8")
    git(other_clone, "add", "from_other.txt")
    git(other_clone, "commit", "-m", "other commit")
    git(other_clone, "push", "origin", "HEAD:main")

    (repo_with_upstream / "local.txt").write_text("local only\n", encoding="utf-8")
    git(repo_with_upstream, "add", "local.txt")
    git(repo_with_upstream, "commit", "-m", "local commit")
    repo = RepoConfig(name="repo", path=repo_with_upstream)

    snapshot = scan_repo(repo, fetch=True, fetch_timeout_seconds=20)

    assert snapshot.remote.ahead == 1
    assert snapshot.remote.behind == 1
    assert "ahead_remote" in snapshot.risk_flags
    assert "behind_remote" in snapshot.risk_flags
    assert "diverged_remote" in snapshot.risk_flags


def test_remote_check_disabled_skips_remote_entirely(clean_git_repo: Path) -> None:
    repo = RepoConfig(name="repo", path=clean_git_repo)

    snapshot = scan_repo(repo, remote_check=False)

    assert snapshot.remote == RemoteSyncStatus()
    assert "no_upstream" not in snapshot.risk_flags
    assert "ahead_remote" not in snapshot.risk_flags


def test_fetch_disabled_by_default_makes_no_network_attempt(repo_with_upstream: Path) -> None:
    git(repo_with_upstream, "remote", "set-url", "origin", "/does/not/exist.git")
    repo = RepoConfig(name="repo", path=repo_with_upstream)

    snapshot = scan_repo(repo, fetch=False)

    assert snapshot.remote.fetched is False
    assert snapshot.remote.fetch_error is None


def test_fetch_failure_does_not_crash_build_snapshot(
    tmp_path: Path, repo_with_upstream: Path
) -> None:
    git(repo_with_upstream, "remote", "set-url", "origin", "/does/not/exist.git")
    healthy_repo = tmp_path / "healthy"
    healthy_repo.mkdir()
    git(healthy_repo, "init")
    git(healthy_repo, "config", "user.email", "test@example.com")
    git(healthy_repo, "config", "user.name", "RepoOps Test")
    (healthy_repo / "README.md").write_text("# healthy\n", encoding="utf-8")
    git(healthy_repo, "add", "README.md")
    git(healthy_repo, "commit", "-m", "initial commit")

    config = RepoOpsConfig(
        machine=MachineConfig(name="nasapcdeb"),
        defaults=DefaultsConfig(fetch_timeout_seconds=5),
        repos=[
            RepoConfig(name="broken", path=repo_with_upstream),
            RepoConfig(name="healthy", path=healthy_repo),
        ],
    )

    snapshot = build_snapshot(config, cli_fetch=True)

    broken, healthy = snapshot.repos
    assert broken.remote.fetch_error is not None
    assert "fetch_failed" in broken.risk_flags
    assert healthy.exists is True
    assert healthy.remote.fetch_error is None


def test_sanitize_git_error_redacts_url_and_truncates() -> None:
    raw = "fatal: unable to access 'https://user:token123@example.com/repo.git/': timeout"

    result = _sanitize_git_error(raw)

    assert "token123" not in result
    assert "user:" not in result
    assert "[REDACTED_URL]" in result
    assert len(result) <= 203


def test_sanitize_git_error_empty_input() -> None:
    assert _sanitize_git_error("") == "git fetch failed (no error detail captured)"


def test_run_git_rejects_non_whitelisted_command(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _run_git(tmp_path, ("push", "origin", "main"))


@pytest.mark.parametrize(
    ("cli_fetch", "config_fetch", "expected"),
    [
        (False, False, False),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    ],
)
def test_resolve_fetch_or_semantics(cli_fetch: bool, config_fetch: bool, expected: bool) -> None:
    assert resolve_fetch(cli_fetch, config_fetch) is expected


# --- Risk flags: remote-related ---------------------------------------------


def test_classify_risk_flags_ahead_remote() -> None:
    flags = classify_risk_flags(
        exists=True,
        is_git_repo=True,
        branch="main",
        summary=PorcelainSummary(),
        remote=RemoteSyncStatus(has_upstream=True, ahead=2, behind=0),
    )

    assert "ahead_remote" in flags
    assert "behind_remote" not in flags
    assert "diverged_remote" not in flags


def test_classify_risk_flags_behind_remote() -> None:
    flags = classify_risk_flags(
        exists=True,
        is_git_repo=True,
        branch="main",
        summary=PorcelainSummary(),
        remote=RemoteSyncStatus(has_upstream=True, ahead=0, behind=3),
    )

    assert "behind_remote" in flags
    assert "ahead_remote" not in flags
    assert "diverged_remote" not in flags


def test_classify_risk_flags_diverged_remote() -> None:
    flags = classify_risk_flags(
        exists=True,
        is_git_repo=True,
        branch="main",
        summary=PorcelainSummary(),
        remote=RemoteSyncStatus(has_upstream=True, ahead=1, behind=1),
    )

    assert "ahead_remote" in flags
    assert "behind_remote" in flags
    assert "diverged_remote" in flags


def test_classify_risk_flags_no_upstream() -> None:
    flags = classify_risk_flags(
        exists=True,
        is_git_repo=True,
        branch="main",
        summary=PorcelainSummary(),
        remote=RemoteSyncStatus(has_upstream=False),
    )

    assert "no_upstream" in flags


def test_classify_risk_flags_fetch_failed() -> None:
    flags = classify_risk_flags(
        exists=True,
        is_git_repo=True,
        branch="main",
        summary=PorcelainSummary(),
        remote=RemoteSyncStatus(
            has_upstream=True, ahead=0, behind=0, fetch_error="git fetch timed out"
        ),
    )

    assert "fetch_failed" in flags


def test_classify_risk_flags_remote_check_disabled_suppresses_flags() -> None:
    flags = classify_risk_flags(
        exists=True,
        is_git_repo=True,
        branch="main",
        summary=PorcelainSummary(),
        remote=RemoteSyncStatus(has_upstream=False, fetch_error="boom"),
        remote_check=False,
    )

    assert "no_upstream" not in flags
    assert "fetch_failed" not in flags


# --- Attention score ---------------------------------------------------------


def test_compute_attention_score_clean_repo(repo_with_upstream: Path) -> None:
    snapshot = scan_repo(RepoConfig(name="repo", path=repo_with_upstream))

    assert snapshot.attention_score == 0


def test_compute_attention_score_dirty() -> None:
    snapshot = RepoSnapshot(
        name="repo",
        path="/tmp/repo",
        exists=True,
        is_git_repo=True,
        dirty=True,
        risk_flags=["dirty"],
    )

    assert compute_attention_score(snapshot) == 30


def test_compute_attention_score_possible_secret_file() -> None:
    snapshot = RepoSnapshot(
        name="repo",
        path="/tmp/repo",
        exists=True,
        is_git_repo=True,
        risk_flags=["possible_secret_file"],
    )

    assert compute_attention_score(snapshot) == 70


def test_compute_attention_score_conflicted_uses_counts() -> None:
    snapshot = RepoSnapshot(
        name="repo",
        path="/tmp/repo",
        exists=True,
        is_git_repo=True,
        counts=ChangeCounts(conflicted=1),
        risk_flags=[],
    )

    assert compute_attention_score(snapshot) == 80


def test_compute_attention_score_repo_missing(tmp_path: Path) -> None:
    snapshot = scan_repo(RepoConfig(name="missing", path=tmp_path / "does-not-exist"))

    assert snapshot.attention_score == 100


def test_compute_attention_score_ordering() -> None:
    diverged = RepoSnapshot(
        name="diverged",
        path="/tmp/diverged",
        exists=True,
        is_git_repo=True,
        risk_flags=["diverged_remote", "ahead_remote", "behind_remote"],
    )
    dirty = RepoSnapshot(
        name="dirty",
        path="/tmp/dirty",
        exists=True,
        is_git_repo=True,
        risk_flags=["dirty"],
    )
    untracked = RepoSnapshot(
        name="untracked",
        path="/tmp/untracked",
        exists=True,
        is_git_repo=True,
        risk_flags=["untracked_files"],
    )

    scores = {
        "diverged": compute_attention_score(diverged),
        "dirty": compute_attention_score(dirty),
        "untracked": compute_attention_score(untracked),
    }

    assert scores["diverged"] > scores["dirty"] > scores["untracked"]
