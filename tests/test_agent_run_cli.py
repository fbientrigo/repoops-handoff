from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repoops.cli import app

runner_cli = CliRunner()

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "agy_stream"


class FakePopen:
    def __init__(self, lines: list[str], returncode: int = 0) -> None:
        self.stdout = iter(lines)
        self.stderr = io.StringIO("")
        self._returncode = returncode

    def wait(self, timeout: float | None = None) -> int:
        return self._returncode


def test_agent_run_cli_executes_mocked_task_end_to_end(
    monkeypatch: pytest.MonkeyPatch, clean_git_repo: Path, tmp_path: Path
) -> None:
    lines = (FIXTURES_DIR / "success.ndjson").read_text(encoding="utf-8").splitlines(keepends=True)
    monkeypatch.setattr(
        "repoops.agent_runner._spawn_agy", lambda *a, **k: FakePopen(lines, returncode=0)
    )
    monkeypatch.setattr("repoops.agy_cli.require_agy", lambda *a, **k: "agy")

    prompt_file = tmp_path / "task.txt"
    prompt_file.write_text("Implement the feature.\n", encoding="utf-8")

    result = runner_cli.invoke(
        app,
        [
            "agent-run",
            str(clean_git_repo),
            "--provider",
            "antigravity",
            "--model",
            "gemini-2.5-pro",
            "--prompt-file",
            str(prompt_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Process exit status: success" in result.output
    assert "Agent-reported status: success" in result.output

    run_dirs = list((clean_git_repo / ".repoops" / "agent-runs").iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "run.json").exists()
    assert (run_dirs[0] / "stream.ndjson").exists()


def test_agent_run_cli_rejects_unsupported_provider(tmp_path: Path, clean_git_repo: Path) -> None:
    prompt_file = tmp_path / "task.txt"
    prompt_file.write_text("Implement the feature.\n", encoding="utf-8")

    result = runner_cli.invoke(
        app,
        [
            "agent-run",
            str(clean_git_repo),
            "--provider",
            "codex",
            "--model",
            "x",
            "--prompt-file",
            str(prompt_file),
        ],
    )

    assert result.exit_code == 1
    assert "unsupported provider" in result.output


def test_agent_run_cli_executes_task_contract(
    monkeypatch: pytest.MonkeyPatch, clean_git_repo: Path, tmp_path: Path
) -> None:
    lines = (FIXTURES_DIR / "success.ndjson").read_text(encoding="utf-8").splitlines(keepends=True)
    monkeypatch.setattr(
        "repoops.agent_runner._spawn_agy", lambda *a, **k: FakePopen(lines, returncode=0)
    )
    monkeypatch.setattr("repoops.agy_cli.require_agy", lambda *a, **k: "agy")

    task_file = tmp_path / "task.yaml"
    task_file.write_text(
        f"""
id: cli-task-test
objective: Create test file
expected_changes:
  required: false
allowed_paths:
  - tests/
acceptance:
  - {sys.executable} -c 'print("CLI acceptance ok")'
""",
        encoding="utf-8",
    )

    result = runner_cli.invoke(
        app,
        [
            "agent-run",
            str(clean_git_repo),
            "--provider",
            "antigravity",
            "--model",
            "gemini-2.5-pro",
            "--task",
            str(task_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Process exit status: success" in result.output
    assert "Workspace policy status: passed" in result.output
    assert "Acceptance status: passed" in result.output
    assert "RepoOps Verdict: verified" in result.output
