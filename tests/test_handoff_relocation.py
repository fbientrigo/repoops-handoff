"""Repository relocation / remote-identity contracts (P0 hardening fix 3).

Covers `normalize_remote_identity` directly, and the resume drift severity rules for
a repository checked out at a different absolute path with an equivalent, different,
or unavailable Git remote.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import git
from repoops.cli import app
from repoops.handoff import create_checkpoint, handoff_paths, normalize_remote_identity, run_resume
from repoops.handoff_models import Severity

runner = CliRunner()


# --- normalize_remote_identity: unit-level equivalence and security --------------


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:owner/repo.git",
        "https://github.com/owner/repo.git",
        "ssh://git@github.com/owner/repo.git",
        "https://github.com/owner/repo",
        "git@github.com:owner/repo",
        "ssh://git@github.com:22/owner/repo.git",
        "https://github.com/owner/repo.git/",
    ],
)
def test_equivalent_remote_forms_normalize_to_the_same_identity(url: str) -> None:
    assert normalize_remote_identity(url) == "github.com/owner/repo"


def test_different_owner_normalizes_differently() -> None:
    a = normalize_remote_identity("git@github.com:owner/repo.git")
    b = normalize_remote_identity("https://github.com/someone-else/repo.git")
    assert a != b


def test_different_host_normalizes_differently() -> None:
    a = normalize_remote_identity("https://github.com/owner/repo.git")
    b = normalize_remote_identity("https://gitlab.com/owner/repo.git")
    assert a != b


def test_normalize_remote_identity_none_and_empty() -> None:
    assert normalize_remote_identity(None) is None
    assert normalize_remote_identity("") is None
    assert normalize_remote_identity("   ") is None


def test_normalize_remote_identity_unparseable_local_path() -> None:
    assert normalize_remote_identity("/home/user/bare-repos/repo.git") is None


def test_normalize_strips_https_credentials() -> None:
    identity = normalize_remote_identity(
        "https://oauth2:ghp_supersecrettoken123@github.com/owner/repo.git"
    )
    assert identity == "github.com/owner/repo"
    assert "ghp_supersecrettoken123" not in identity
    assert "oauth2" not in identity


def test_normalize_strips_query_string() -> None:
    identity = normalize_remote_identity("https://github.com/owner/repo.git?token=abcdef123456")
    assert identity == "github.com/owner/repo"
    assert "abcdef123456" not in identity


def test_normalize_strips_username_password() -> None:
    identity = normalize_remote_identity("https://user:hunter2@github.com/owner/repo.git")
    assert identity == "github.com/owner/repo"
    assert "hunter2" not in identity
    assert "user" not in identity.split("/")[0]


# --- relocation drift severities via run_resume -----------------------------------


def _init_repo_with_remote(path: Path, remote_url: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "RepoOps Test")
    git(path, "remote", "add", "origin", remote_url)
    (path / "README.md").write_text("# test repo\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-m", "initial commit")
    return path


def test_same_root_same_remote_no_relocation_drift(tmp_path: Path) -> None:
    repo = _init_repo_with_remote(
        tmp_path / "repo", "git@github.com:fbientrigo/repoops-handoff.git"
    )
    create_checkpoint(repo)

    report = run_resume(repo)

    assert report.overall_severity == Severity.NONE
    fields = {item.field for item in report.drift_items}
    assert "repository_relocated" not in fields
    assert "repository_root" not in fields


def test_relocation_with_equivalent_remote_is_warning_not_blocking(tmp_path: Path) -> None:
    checkout_a = _init_repo_with_remote(
        tmp_path / "checkout-a", "git@github.com:fbientrigo/repoops-handoff.git"
    )
    create_checkpoint(checkout_a)
    recorded_json, _ = handoff_paths(checkout_a)

    checkout_b = _init_repo_with_remote(
        tmp_path / "checkout-b", "https://github.com/fbientrigo/repoops-handoff.git"
    )
    other_json, _ = handoff_paths(checkout_b)
    other_json.parent.mkdir(parents=True, exist_ok=True)
    other_json.write_text(recorded_json.read_text(encoding="utf-8"), encoding="utf-8")

    report = run_resume(checkout_b)

    assert report.overall_severity == Severity.WARNING
    assert report.exit_code == 0
    relocated = next(item for item in report.drift_items if item.field == "repository_relocated")
    assert relocated.severity == Severity.WARNING
    assert str(checkout_a.resolve()) in str(relocated.old)
    assert str(checkout_b.resolve()) in str(relocated.new)


def test_relocation_cli_exit_code_zero_with_matching_remote(tmp_path: Path) -> None:
    checkout_a = _init_repo_with_remote(
        tmp_path / "checkout-a", "git@github.com:fbientrigo/repoops-handoff.git"
    )
    create_checkpoint(checkout_a)
    recorded_json, _ = handoff_paths(checkout_a)

    checkout_b = _init_repo_with_remote(
        tmp_path / "checkout-b", "https://github.com/fbientrigo/repoops-handoff.git"
    )
    other_json, _ = handoff_paths(checkout_b)
    other_json.parent.mkdir(parents=True, exist_ok=True)
    other_json.write_text(recorded_json.read_text(encoding="utf-8"), encoding="utf-8")

    result = runner.invoke(app, ["resume", str(checkout_b)])

    assert result.exit_code == 0, result.output
    assert "WARNING" in result.output
    assert "repository_relocated" in result.output or "relocation" in result.output.lower()


def test_relocation_with_different_remote_is_blocking(tmp_path: Path) -> None:
    checkout_a = _init_repo_with_remote(
        tmp_path / "checkout-a", "git@github.com:fbientrigo/repoops-handoff.git"
    )
    create_checkpoint(checkout_a)
    recorded_json, _ = handoff_paths(checkout_a)

    wrong_repo = _init_repo_with_remote(
        tmp_path / "wrong-repo", "https://github.com/example/not-the-same-repository.git"
    )
    other_json, _ = handoff_paths(wrong_repo)
    other_json.parent.mkdir(parents=True, exist_ok=True)
    other_json.write_text(recorded_json.read_text(encoding="utf-8"), encoding="utf-8")

    report = run_resume(wrong_repo)

    assert report.overall_severity == Severity.BLOCKING
    assert report.exit_code == 1
    root_item = next(item for item in report.drift_items if item.field == "repository_root")
    assert root_item.severity == Severity.BLOCKING


def test_relocation_cli_nonzero_exit_with_different_remote(tmp_path: Path) -> None:
    checkout_a = _init_repo_with_remote(
        tmp_path / "checkout-a", "git@github.com:fbientrigo/repoops-handoff.git"
    )
    create_checkpoint(checkout_a)
    recorded_json, _ = handoff_paths(checkout_a)

    wrong_repo = _init_repo_with_remote(
        tmp_path / "wrong-repo", "https://github.com/example/not-the-same-repository.git"
    )
    other_json, _ = handoff_paths(wrong_repo)
    other_json.parent.mkdir(parents=True, exist_ok=True)
    other_json.write_text(recorded_json.read_text(encoding="utf-8"), encoding="utf-8")

    result = runner.invoke(app, ["resume", str(wrong_repo)])

    assert result.exit_code != 0
    assert "BLOCKING" in result.output


def test_relocation_with_no_remote_configured_is_blocking(tmp_path: Path) -> None:
    checkout_a = _init_repo_with_remote(
        tmp_path / "checkout-a", "git@github.com:fbientrigo/repoops-handoff.git"
    )
    create_checkpoint(checkout_a)
    recorded_json, _ = handoff_paths(checkout_a)

    no_remote_repo = tmp_path / "no-remote"
    no_remote_repo.mkdir()
    git(no_remote_repo, "init")
    git(no_remote_repo, "config", "user.email", "test@example.com")
    git(no_remote_repo, "config", "user.name", "RepoOps Test")
    (no_remote_repo / "README.md").write_text("# test\n", encoding="utf-8")
    git(no_remote_repo, "add", "README.md")
    git(no_remote_repo, "commit", "-m", "initial commit")

    other_json, _ = handoff_paths(no_remote_repo)
    other_json.parent.mkdir(parents=True, exist_ok=True)
    other_json.write_text(recorded_json.read_text(encoding="utf-8"), encoding="utf-8")

    report = run_resume(no_remote_repo)

    assert report.overall_severity == Severity.BLOCKING
    assert report.exit_code == 1


def test_remote_identity_changed_at_same_root_is_at_least_warning(tmp_path: Path) -> None:
    repo = _init_repo_with_remote(
        tmp_path / "repo", "git@github.com:fbientrigo/repoops-handoff.git"
    )
    create_checkpoint(repo)

    git(repo, "remote", "set-url", "origin", "https://github.com/example/different-repo.git")

    report = run_resume(repo)

    assert report.overall_severity in (Severity.WARNING, Severity.BLOCKING)
    fields = {item.field: item for item in report.drift_items}
    assert "remote_identity" in fields
    # Both sides are non-empty and clearly different -> BLOCKING per the drift rules.
    assert fields["remote_identity"].severity == Severity.BLOCKING


# --- secrets never leak into any generated artifact -------------------------------


def test_secret_remote_credentials_never_appear_in_checkpoint_or_resume_output(
    tmp_path: Path,
) -> None:
    secret_url = "https://oauth2:ghp_supersecrettoken123@github.com/fbientrigo/repoops-handoff.git"
    repo = _init_repo_with_remote(tmp_path / "repo", secret_url)

    handoff = create_checkpoint(repo)
    json_path, md_path = handoff_paths(repo)

    assert "ghp_supersecrettoken123" not in json_path.read_text(encoding="utf-8")
    assert "ghp_supersecrettoken123" not in md_path.read_text(encoding="utf-8")
    assert "ghp_supersecrettoken123" not in handoff.model_dump_json()

    result = runner.invoke(app, ["resume", str(repo)])
    assert "ghp_supersecrettoken123" not in result.output

    checkpoint_result = runner.invoke(app, ["checkpoint", str(repo)])
    assert "ghp_supersecrettoken123" not in checkpoint_result.output
