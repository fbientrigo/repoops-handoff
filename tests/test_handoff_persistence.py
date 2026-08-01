"""Semantic-preservation, explicit-reset, and invalid-existing-state contracts for
`repoops checkpoint` (P0 hardening fixes 1 and 2)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoops.cli import app
from repoops.handoff import HandoffError, create_checkpoint, handoff_paths
from repoops.handoff_models import HANDOFF_SCHEMA_VERSION

runner = CliRunner()


def _fill_semantic_fields(json_path: Path) -> dict:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["semantic"] = {
        "goal": "Ship the relocation-aware handoff.",
        "current_scope": "handoff.py, handoff_render.py, handoff_models.py, cli.py",
        "out_of_scope": ["cloud sync", "LLM calls"],
        "completed": ["Added remote identity normalization"],
        "decisions": [{"decision": "Use host/owner/repo as identity", "rationale": "stable"}],
        "failed_attempts": [{"attempt": "Compare raw URLs", "why_failed": "syntax varies"}],
        "verification_passed": [{"check": "ruff check .", "result": "pass"}],
        "verification_pending": [{"check": "pytest -k relocation", "result": "not yet run"}],
    }
    data["next_action"] = {
        "task": "Write the relocation tests",
        "command": "pytest tests/test_handoff_relocation.py",
        "success_condition": "All relocation tests pass",
        "blocker": None,
    }
    json_path.write_text(json.dumps(data), encoding="utf-8")
    return data


# --- semantic preservation across repeated checkpoints --------------------------


def test_second_checkpoint_preserves_edited_semantic_fields(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    json_path, md_path = handoff_paths(clean_git_repo)
    edited = _fill_semantic_fields(json_path)

    (clean_git_repo / "more.txt").write_text("more work\n", encoding="utf-8")

    handoff = create_checkpoint(clean_git_repo)

    assert handoff.semantic.goal == edited["semantic"]["goal"]
    assert handoff.semantic.current_scope == edited["semantic"]["current_scope"]
    assert handoff.semantic.out_of_scope == edited["semantic"]["out_of_scope"]
    assert handoff.semantic.completed == edited["semantic"]["completed"]
    assert handoff.semantic.decisions == edited["semantic"]["decisions"]
    assert handoff.semantic.failed_attempts == edited["semantic"]["failed_attempts"]
    assert handoff.semantic.verification_passed == edited["semantic"]["verification_passed"]
    assert handoff.semantic.verification_pending == edited["semantic"]["verification_pending"]
    assert handoff.next_action.task == edited["next_action"]["task"]
    assert handoff.next_action.command == edited["next_action"]["command"]
    assert handoff.next_action.success_condition == edited["next_action"]["success_condition"]

    # Deterministic Git facts and timestamp are refreshed, not preserved.
    assert handoff.changes.counts.untracked == 1
    assert "more.txt" in handoff.changes.notable_paths

    md_content = md_path.read_text(encoding="utf-8")
    assert edited["semantic"]["goal"] in md_content
    assert "Use host/owner/repo as identity" in md_content
    assert "Compare raw URLs" in md_content
    assert "pytest -k relocation" in md_content
    assert "not yet run" in md_content
    assert "TODO:" not in md_content


def test_second_checkpoint_refreshes_git_facts(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    json_path, _ = handoff_paths(clean_git_repo)
    first = json.loads(json_path.read_text(encoding="utf-8"))

    (clean_git_repo / "more.txt").write_text("more work\n", encoding="utf-8")
    handoff = create_checkpoint(clean_git_repo)

    # created_at is recomputed on every checkpoint (may equal the prior value if both
    # runs land within the same second-resolution timestamp -- that's still "refreshed",
    # just coincidentally identical). What must actually change is the worktree facts.
    assert handoff.created_at >= first["created_at"]
    assert handoff.repository.dirty is True
    assert handoff.changes.counts.untracked == 1
    assert first["repository"]["dirty"] is False


def test_resume_after_second_checkpoint_shows_preserved_values(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    json_path, _ = handoff_paths(clean_git_repo)
    edited = _fill_semantic_fields(json_path)
    create_checkpoint(clean_git_repo)

    result = runner.invoke(app, ["resume", str(clean_git_repo)])

    assert result.exit_code == 0, result.output
    assert edited["semantic"]["goal"] in result.output
    assert "Use host/owner/repo as identity" in result.output
    assert "Compare raw URLs" in result.output
    assert edited["next_action"]["success_condition"] in result.output


# --- explicit --reset-semantic ----------------------------------------------------


def test_reset_semantic_replaces_existing_context_with_placeholders(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    json_path, _ = handoff_paths(clean_git_repo)
    _fill_semantic_fields(json_path)

    handoff = create_checkpoint(clean_git_repo, reset_semantic=True)

    assert handoff.semantic.goal.startswith("TODO:")
    assert handoff.semantic.decisions == []
    assert handoff.next_action.task.startswith("TODO:")
    assert handoff.next_action.command is None


def test_default_checkpoint_does_not_reset_without_flag(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    json_path, _ = handoff_paths(clean_git_repo)
    edited = _fill_semantic_fields(json_path)

    handoff = create_checkpoint(clean_git_repo)

    assert handoff.semantic.goal == edited["semantic"]["goal"]
    assert not handoff.semantic.goal.startswith("TODO:")


def test_reset_semantic_cli_flag(clean_git_repo: Path) -> None:
    runner.invoke(app, ["checkpoint", str(clean_git_repo)])
    json_path, _ = handoff_paths(clean_git_repo)
    _fill_semantic_fields(json_path)

    result = runner.invoke(app, ["checkpoint", str(clean_git_repo), "--reset-semantic"])

    assert result.exit_code == 0, result.output
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["semantic"]["goal"].startswith("TODO:")


# --- invalid existing handoff.json -------------------------------------------------


def test_checkpoint_fails_on_invalid_json_without_reset(clean_git_repo: Path) -> None:
    json_path, md_path = handoff_paths(clean_git_repo)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(HandoffError):
        create_checkpoint(clean_git_repo)

    assert json_path.read_text(encoding="utf-8") == "{not valid json"
    assert not md_path.exists()


def test_checkpoint_fails_on_unsupported_schema_without_reset(clean_git_repo: Path) -> None:
    create_checkpoint(clean_git_repo)
    json_path, _ = handoff_paths(clean_git_repo)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["schema_version"] = "repoops.handoff.v99"
    original_text = json.dumps(data)
    json_path.write_text(original_text, encoding="utf-8")

    with pytest.raises(HandoffError):
        create_checkpoint(clean_git_repo)

    assert json_path.read_text(encoding="utf-8") == original_text


def test_checkpoint_fails_on_structurally_invalid_handoff_without_reset(
    clean_git_repo: Path,
) -> None:
    json_path, _ = handoff_paths(clean_git_repo)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    original_text = json.dumps({"schema_version": HANDOFF_SCHEMA_VERSION, "created_at": "now"})
    json_path.write_text(original_text, encoding="utf-8")

    with pytest.raises(HandoffError):
        create_checkpoint(clean_git_repo)

    assert json_path.read_text(encoding="utf-8") == original_text


def test_checkpoint_cli_nonzero_exit_on_invalid_existing_json(clean_git_repo: Path) -> None:
    json_path, md_path = handoff_paths(clean_git_repo)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text("{not valid json", encoding="utf-8")

    result = runner.invoke(app, ["checkpoint", str(clean_git_repo)])

    assert result.exit_code != 0
    assert json_path.read_text(encoding="utf-8") == "{not valid json"
    assert not md_path.exists()


def test_reset_semantic_recovers_from_invalid_existing_json(clean_git_repo: Path) -> None:
    json_path, md_path = handoff_paths(clean_git_repo)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text("{not valid json", encoding="utf-8")

    handoff = create_checkpoint(clean_git_repo, reset_semantic=True)

    assert handoff.semantic.goal.startswith("TODO:")
    assert json_path.exists()
    assert md_path.exists()
    json.loads(json_path.read_text(encoding="utf-8"))  # now valid


def test_checkpoint_fails_when_existing_handoff_belongs_to_another_repository(
    clean_git_repo: Path, tmp_path: Path
) -> None:
    from conftest import git

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

    other_json, other_md = handoff_paths(other_repo)
    other_json.parent.mkdir(parents=True, exist_ok=True)
    original_text = recorded_json.read_text(encoding="utf-8")
    other_json.write_text(original_text, encoding="utf-8")

    with pytest.raises(HandoffError):
        create_checkpoint(other_repo)

    assert other_json.read_text(encoding="utf-8") == original_text
    assert not other_md.exists()
