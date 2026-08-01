import json
from pathlib import Path

from typer.testing import CliRunner

from conftest import git
from repoops.cli import app
from repoops.handoff import (
    HANDOFF_JSON_NAME,
    HANDOFF_MD_NAME,
    create_checkpoint,
    handoff_paths,
    run_resume,
)
from repoops.handoff_models import HANDOFF_SCHEMA_VERSION, Severity

runner = CliRunner()


# --- checkpoint: clean repository --------------------------------------------


def test_checkpoint_creates_files_in_clean_repo(clean_git_repo: Path) -> None:
    handoff = create_checkpoint(clean_git_repo)

    json_path, md_path = handoff_paths(clean_git_repo)
    assert json_path.exists()
    assert md_path.exists()
    assert json_path.name == HANDOFF_JSON_NAME
    assert md_path.name == HANDOFF_MD_NAME

    assert handoff.schema_version == HANDOFF_SCHEMA_VERSION
    assert handoff.repository.root == str(clean_git_repo.resolve())
    assert handoff.repository.dirty is False
    assert handoff.changes.counts.modified == 0
    assert handoff.changes.counts.staged == 0
    assert handoff.changes.counts.untracked == 0
    assert handoff.semantic.goal.startswith("TODO:")
    assert handoff.next_action.success_condition.startswith("TODO:")
    assert len(handoff.recent_commits) == 1


def test_checkpoint_markdown_is_readable_and_pasteable(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    _, md_path = handoff_paths(clean_git_repo)

    content = md_path.read_text(encoding="utf-8")
    assert content.startswith("# repoops handoff")
    assert "## Repository" in content
    assert "## Next action" in content
    assert "TODO:" in content


# --- checkpoint: dirty repository, staged and untracked ----------------------


def test_checkpoint_creates_files_in_dirty_repo(clean_git_repo: Path) -> None:
    (clean_git_repo / "README.md").write_text("# changed\n", encoding="utf-8")
    (clean_git_repo / "notes.txt").write_text("scratch\n", encoding="utf-8")

    handoff = create_checkpoint(clean_git_repo)

    assert handoff.repository.dirty is True
    assert handoff.changes.counts.modified == 1
    assert handoff.changes.counts.untracked == 1
    assert "README.md" in handoff.changes.diff_stat
    assert "modified" not in handoff.changes.diff_stat  # only stat, no diff verb noise


def test_checkpoint_records_staged_and_untracked_changes(clean_git_repo: Path) -> None:
    (clean_git_repo / "staged.txt").write_text("staged content\n", encoding="utf-8")
    git(clean_git_repo, "add", "staged.txt")
    (clean_git_repo / "loose.txt").write_text("untracked content\n", encoding="utf-8")

    handoff = create_checkpoint(clean_git_repo)

    assert handoff.changes.counts.staged == 1
    assert handoff.changes.counts.untracked == 1
    assert "staged.txt" in handoff.changes.cached_diff_stat
    assert "staged.txt" in handoff.changes.notable_paths
    assert "loose.txt" in handoff.changes.notable_paths


# --- checkpoint: detached HEAD -------------------------------------------------


def test_checkpoint_detects_detached_head(clean_git_repo: Path) -> None:
    head = git(clean_git_repo, "rev-parse", "HEAD").stdout.strip()
    git(clean_git_repo, "checkout", head)

    handoff = create_checkpoint(clean_git_repo)

    assert handoff.repository.detached_head is True
    assert handoff.repository.branch is None


# --- checkpoint: repository discovery from a subdirectory --------------------


def test_checkpoint_discovers_root_from_subdirectory(clean_git_repo: Path) -> None:
    sub = clean_git_repo / "src" / "pkg"
    sub.mkdir(parents=True)
    (sub / "module.py").write_text("x = 1\n", encoding="utf-8")

    handoff = create_checkpoint(sub)

    assert handoff.repository.root == str(clean_git_repo.resolve())
    json_path, md_path = handoff_paths(clean_git_repo)
    assert json_path.exists()
    assert md_path.exists()


# --- checkpoint: secret-like path redaction -----------------------------------


def test_checkpoint_redacts_secret_like_paths(clean_git_repo: Path) -> None:
    (clean_git_repo / ".env").write_text("TOKEN=abc123\n", encoding="utf-8")
    secrets_dir = clean_git_repo / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "api_token.txt").write_text("shh\n", encoding="utf-8")

    handoff = create_checkpoint(clean_git_repo)

    assert "[REDACTED_SECRET_PATH]" in handoff.changes.notable_paths
    assert ".env" not in handoff.changes.notable_paths
    assert not any("api_token" in p for p in handoff.changes.notable_paths)
    assert "abc123" not in handoff.model_dump_json()
    _, md_path = handoff_paths(clean_git_repo)
    md_content = md_path.read_text(encoding="utf-8")
    assert "abc123" not in md_content
    assert ".env" not in md_content


def test_checkpoint_redacts_secret_like_paths_in_diff_stat(clean_git_repo: Path) -> None:
    (clean_git_repo / "config.credentials.json").write_text("{}\n", encoding="utf-8")
    git(clean_git_repo, "add", "config.credentials.json")
    git(clean_git_repo, "commit", "-m", "add secret-looking file")
    (clean_git_repo / "config.credentials.json").write_text('{"x": 1}\n', encoding="utf-8")

    handoff = create_checkpoint(clean_git_repo)

    assert "credentials" not in handoff.changes.diff_stat
    assert "[REDACTED_SECRET_PATH]" in handoff.changes.diff_stat


def test_checkpoint_never_creates_extra_untracked_drift(clean_git_repo: Path) -> None:
    """Writing the checkpoint itself must not show up as new drift on the next scan."""
    create_checkpoint(clean_git_repo)

    report = run_resume(clean_git_repo)

    assert report.overall_severity == Severity.NONE
    assert report.drift_items == []


# --- resume: no drift ---------------------------------------------------------


def test_resume_reports_no_drift_immediately_after_checkpoint(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)

    report = run_resume(clean_git_repo)

    assert report.overall_severity == Severity.NONE
    assert report.exit_code == 0
    assert report.recorded is not None


def test_resume_cli_no_drift_exit_zero(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)

    result = runner.invoke(app, ["resume", str(clean_git_repo)])

    assert result.exit_code == 0, result.output
    assert "RECORDED HANDOFF" in result.output
    assert "CURRENT REPOSITORY STATE" in result.output
    assert "DRIFT DETECTED" in result.output
    assert "NEXT ACTION" in result.output
    assert "NONE" in result.output


# --- resume: branch change -----------------------------------------------------


def test_resume_detects_branch_change(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    git(clean_git_repo, "checkout", "-b", "feature/other")

    report = run_resume(clean_git_repo)

    assert report.overall_severity == Severity.BLOCKING
    assert report.exit_code == 1
    fields = {item.field for item in report.drift_items}
    assert "branch" in fields
    branch_item = next(item for item in report.drift_items if item.field == "branch")
    assert branch_item.severity == Severity.BLOCKING


# --- resume: HEAD change --------------------------------------------------------


def test_resume_detects_head_change_same_branch(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    (clean_git_repo / "more.txt").write_text("more\n", encoding="utf-8")
    git(clean_git_repo, "add", "more.txt")
    git(clean_git_repo, "commit", "-m", "second commit")

    report = run_resume(clean_git_repo)

    fields = {item.field: item for item in report.drift_items}
    assert "head" in fields
    assert fields["head"].severity in (Severity.WARNING, Severity.BLOCKING)
    assert fields["head"].old != fields["head"].new
    assert "branch" not in fields


def test_resume_cli_head_change_exit_code_reflects_severity(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    (clean_git_repo / "more.txt").write_text("more\n", encoding="utf-8")
    git(clean_git_repo, "add", "more.txt")
    git(clean_git_repo, "commit", "-m", "second commit")

    result = runner.invoke(app, ["resume", str(clean_git_repo)])

    # HEAD-only change on the same branch is WARNING, not BLOCKING -> exit 0.
    assert result.exit_code == 0, result.output
    assert "WARNING" in result.output


# --- resume: dirty-only drift is WARNING, not BLOCKING --------------------------


def test_resume_dirty_count_change_is_warning_not_blocking(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    (clean_git_repo / "scratch.txt").write_text("wip\n", encoding="utf-8")

    report = run_resume(clean_git_repo)

    assert report.overall_severity == Severity.WARNING
    assert report.exit_code == 0
    fields = {item.field for item in report.drift_items}
    assert "worktree_state" in fields


# --- resume: invalid JSON -------------------------------------------------------


def test_resume_invalid_json_is_blocking(clean_git_repo: Path) -> None:
    json_path, _ = handoff_paths(clean_git_repo)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text("{not valid json", encoding="utf-8")

    report = run_resume(clean_git_repo)

    assert report.overall_severity == Severity.BLOCKING
    assert report.exit_code == 1
    assert report.recorded is None
    assert any(item.field == "handoff_schema" for item in report.drift_items)


def test_resume_missing_handoff_is_blocking(clean_git_repo: Path) -> None:
    report = run_resume(clean_git_repo)

    assert report.overall_severity == Severity.BLOCKING
    assert report.exit_code == 1
    assert report.recorded is None
    assert any(item.field == "handoff" for item in report.drift_items)


# --- resume: unsupported schema version -----------------------------------------


def test_resume_unsupported_schema_version_is_blocking(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    json_path, _ = handoff_paths(clean_git_repo)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["schema_version"] = "repoops.handoff.v99"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    report = run_resume(clean_git_repo)

    assert report.overall_severity == Severity.BLOCKING
    assert report.exit_code == 1
    assert report.recorded is None
    item = next(item for item in report.drift_items if item.field == "handoff_schema")
    assert "v99" in item.message


def test_resume_malformed_schema_shape_is_blocking(clean_git_repo: Path) -> None:
    json_path, _ = handoff_paths(clean_git_repo)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps({"schema_version": HANDOFF_SCHEMA_VERSION, "created_at": "now"}),
        encoding="utf-8",
    )

    report = run_resume(clean_git_repo)

    assert report.overall_severity == Severity.BLOCKING
    assert report.exit_code == 1
    assert any(item.field == "handoff_schema" for item in report.drift_items)


# --- resume: wrong / mismatched repository --------------------------------------


def test_resume_from_wrong_repository_root_is_blocking(
    clean_git_repo: Path, tmp_path: Path
) -> None:
    create_checkpoint(clean_git_repo)
    recorded_json, _ = handoff_paths(clean_git_repo)

    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()
    git(other_repo, "init")
    git(other_repo, "config", "user.email", "test@example.com")
    git(other_repo, "config", "user.name", "RepoOps Test")
    (other_repo / "README.md").write_text("# other\n", encoding="utf-8")
    git(other_repo, "add", "README.md")
    git(other_repo, "commit", "-m", "initial commit")

    other_json, _ = handoff_paths(other_repo)
    other_json.parent.mkdir(parents=True, exist_ok=True)
    other_json.write_text(recorded_json.read_text(encoding="utf-8"), encoding="utf-8")

    report = run_resume(other_repo)

    assert report.overall_severity == Severity.BLOCKING
    assert report.exit_code == 1
    root_item = next(item for item in report.drift_items if item.field == "repository_root")
    assert root_item.severity == Severity.BLOCKING
    assert root_item.old == str(clean_git_repo.resolve())
    assert root_item.new == str(other_repo.resolve())


# --- non-zero exit code for blocking drift (CLI) --------------------------------


def test_resume_cli_exit_code_nonzero_for_blocking_drift(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    git(clean_git_repo, "checkout", "-b", "feature/other")

    result = runner.invoke(app, ["resume", str(clean_git_repo)])

    assert result.exit_code != 0
    assert "BLOCKING" in result.output


def test_checkpoint_cli_reports_written_paths(clean_git_repo: Path) -> None:
    result = runner.invoke(app, ["checkpoint", str(clean_git_repo)])

    assert result.exit_code == 0, result.output
    json_path, md_path = handoff_paths(clean_git_repo)
    assert str(json_path) in result.output
    assert str(md_path) in result.output


def test_resume_outside_git_repo_errors(tmp_path: Path) -> None:
    non_git = tmp_path / "plain"
    non_git.mkdir()

    result = runner.invoke(app, ["resume", str(non_git)])

    assert result.exit_code != 0


# --- preservation of unrelated existing functionality ---------------------------


def test_scan_command_still_works_unaffected_by_handoff(
    tmp_path: Path, clean_git_repo: Path
) -> None:
    config_path = tmp_path / "repos.yaml"
    config_path.write_text(
        f"""
        machine:
          name: nasapcdeb
        repos:
          - name: repo
            path: {clean_git_repo}
        """,
        encoding="utf-8",
    )

    result = runner.invoke(app, ["scan", "--config", str(config_path)])

    assert result.exit_code == 0, result.output


# --- Markdown contract: JSON is canonical, Markdown is generated ----------------


def test_markdown_states_json_is_canonical_and_not_hand_editable(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    _, md_path = handoff_paths(clean_git_repo)
    content = md_path.read_text(encoding="utf-8")

    # The notice must be prominent near the top, not just mentioned somewhere.
    header_and_notice = content.split("## Repository", 1)[0]
    assert "handoff.json" in header_and_notice
    assert "canonical" in header_and_notice.lower() or "generated" in header_and_notice.lower()
    assert "not" in header_and_notice.lower()
    assert "repoops resume" in header_and_notice or "`repoops resume`" in header_and_notice


def test_markdown_renders_full_semantic_content_not_just_counts(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    json_path, md_path = handoff_paths(clean_git_repo)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["semantic"] = {
        "goal": "Full goal text should appear verbatim.",
        "current_scope": "Full scope text should appear verbatim.",
        "out_of_scope": ["Skip networking work"],
        "completed": ["Wrote the parser"],
        "decisions": [
            {"decision": "Use JSON as canonical source", "rationale": "single source of truth"}
        ],
        "failed_attempts": [
            {"attempt": "Parsed Markdown back into JSON", "why_failed": "lossy and fragile"}
        ],
        "verification_passed": [{"check": "ruff check .", "result": "0 errors"}],
        "verification_pending": [{"check": "pytest -q", "result": "not yet run"}],
    }
    json_path.write_text(json.dumps(data), encoding="utf-8")

    create_checkpoint(clean_git_repo)
    content = md_path.read_text(encoding="utf-8")

    assert "Full goal text should appear verbatim." in content
    assert "Full scope text should appear verbatim." in content
    assert "Skip networking work" in content
    assert "Wrote the parser" in content
    assert "Use JSON as canonical source" in content
    assert "single source of truth" in content
    assert "Parsed Markdown back into JSON" in content
    assert "lossy and fragile" in content
    assert "ruff check ." in content
    assert "0 errors" in content
    assert "pytest -q" in content
    assert "not yet run" in content

    # Must not be reduced to bare counts.
    assert "Decisions: 1" not in content
    assert "Failed attempts: 1" not in content
    assert "Verification passed: 1" not in content
    assert "Verification pending: 1" not in content


# --- resume content: full semantic detail, not just goal/completed-count --------


def test_resume_output_includes_decisions_and_failed_attempts(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    json_path, _ = handoff_paths(clean_git_repo)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["semantic"]["decisions"] = [{"decision": "Adopt normalized remote identity"}]
    data["semantic"]["failed_attempts"] = [{"attempt": "Trusted raw remote URL equality"}]
    data["semantic"]["verification_passed"] = [
        {"check": "unit tests for normalize_remote_identity"}
    ]
    data["semantic"]["verification_pending"] = [{"check": "installed wheel smoke test"}]
    data["next_action"]["success_condition"] = "resume exit code is 0 with WARNING only"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    result = runner.invoke(app, ["resume", str(clean_git_repo)])

    assert result.exit_code == 0, result.output
    assert "Adopt normalized remote identity" in result.output
    assert "Trusted raw remote URL equality" in result.output
    assert "unit tests for normalize_remote_identity" in result.output
    assert "installed wheel smoke test" in result.output
    assert "resume exit code is 0 with WARNING only" in result.output


def test_worklog_and_handoff_do_not_interfere(tmp_path: Path, clean_git_repo: Path) -> None:
    worklog_db = tmp_path / "worklog.db"
    config_path = tmp_path / "repos.yaml"
    config_path.write_text(
        f"""
        machine:
          name: nasapcdeb
        defaults:
          worklog_db: {worklog_db}
          remote_check: false
        repos:
          - name: repo
            path: {clean_git_repo}
        """,
        encoding="utf-8",
    )

    create_checkpoint(clean_git_repo)
    scan_result = runner.invoke(app, ["worklog-scan", "--config", str(config_path)])

    assert scan_result.exit_code == 0, scan_result.output
    assert worklog_db.exists()
