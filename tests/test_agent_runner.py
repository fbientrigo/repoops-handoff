from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from repoops.agent_models import AgentRunConfig
from repoops.agent_runner import AntigravityRunner, capture_git_state, diff_git_evidence

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "agy_stream"


def _load_fixture_lines(name: str) -> list[str]:
    text = (FIXTURES_DIR / name).read_text(encoding="utf-8")
    return text.splitlines(keepends=True)


class FakePopen:
    """Stand-in for subprocess.Popen that never spawns a real process."""

    def __init__(self, lines: list[str], returncode: int = 0, stderr_text: str = "") -> None:
        self.stdout = iter(lines)
        self.stderr = io.StringIO(stderr_text)
        self._returncode = returncode

    def wait(self, timeout: float | None = None) -> int:
        return self._returncode


def _patch_popen(
    monkeypatch: pytest.MonkeyPatch, fixture_name: str, *, returncode: int = 0
) -> None:
    lines = _load_fixture_lines(fixture_name)
    monkeypatch.setattr(
        "repoops.agent_runner._spawn_agy",
        lambda *a, **k: FakePopen(lines, returncode=returncode),
    )


# --- successful stream-json run --------------------------------------------------


def test_successful_run_produces_normalized_result(
    monkeypatch: pytest.MonkeyPatch, clean_git_repo: Path
) -> None:
    _patch_popen(monkeypatch, "success.ndjson", returncode=0)
    runner = AntigravityRunner(agy_path="agy")

    result = runner.run(
        task="Add a feature",
        repo=clean_git_repo,
        config=AgentRunConfig(model="gemini-2.5-pro"),
    )

    assert result.provider == "antigravity"
    assert result.requested_model == "gemini-2.5-pro"
    assert result.resolved_model == "gemini-2.5-pro"
    assert result.session_id == "sess_abc123"
    assert result.exit_code == 0
    assert result.process_exit_status == "success"
    assert result.agent_report is not None
    assert result.agent_report.status == "success"
    assert result.usage == {
        "input_tokens": 1200,
        "output_tokens": 340,
        "thinking_tokens": 50,
        "cache_read_tokens": 0,
        "total_tokens": 1590,
    }
    assert "pytest -q" in result.commands_executed
    assert result.malformed_events == []

    run_dir = Path(result.run_dir)
    assert (run_dir / "run.json").exists()
    assert (run_dir / "stream.ndjson").exists()
    assert (run_dir / "report.schema.json").exists()
    persisted = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert persisted["run_id"] == result.run_id


# --- malformed NDJSON event -------------------------------------------------------


def test_malformed_ndjson_line_is_recorded_and_run_continues(
    monkeypatch: pytest.MonkeyPatch, clean_git_repo: Path
) -> None:
    _patch_popen(monkeypatch, "malformed_line.ndjson", returncode=0)
    runner = AntigravityRunner(agy_path="agy")

    result = runner.run(
        task="Add a feature",
        repo=clean_git_repo,
        config=AgentRunConfig(model="gemini-2.5-flash"),
    )

    assert len(result.malformed_events) == 1
    assert result.malformed_events[0].line_number == 2
    assert result.agent_report is not None
    assert result.agent_report.summary == "Done despite one malformed event."


# --- non-zero agy exit -------------------------------------------------------------


def test_non_zero_exit_marks_run_failed(
    monkeypatch: pytest.MonkeyPatch, clean_git_repo: Path
) -> None:
    _patch_popen(monkeypatch, "tool_error.ndjson", returncode=1)
    runner = AntigravityRunner(agy_path="agy")

    result = runner.run(
        task="Add a feature",
        repo=clean_git_repo,
        config=AgentRunConfig(model="gemini-2.5-pro"),
    )

    assert result.exit_code == 1
    assert result.process_exit_status == "failed"
    assert result.verification_notes


# --- result event reporting a fatal ERROR status --------------------------------------


def test_tool_error_event_is_captured(
    monkeypatch: pytest.MonkeyPatch, clean_git_repo: Path
) -> None:
    """`agy` has no distinct `tool_error` NDJSON event; a fatal run only surfaces
    via `result.status == "ERROR"` plus `result.error`, alongside a non-zero exit."""
    _patch_popen(monkeypatch, "tool_error.ndjson", returncode=1)
    runner = AntigravityRunner(agy_path="agy")

    result = runner.run(
        task="Add a feature",
        repo=clean_git_repo,
        config=AgentRunConfig(model="gemini-2.5-pro"),
    )

    assert "pytest reported 2 failed, 10 passed" in result.tool_errors
    assert "pytest -q" in result.commands_executed
    assert result.agent_report is None
    assert result.process_exit_status == "failed"


# --- agent claims success while deterministic evidence indicates failure -----------


def test_agent_reported_success_overridden_by_exit_code(
    monkeypatch: pytest.MonkeyPatch, clean_git_repo: Path
) -> None:
    _patch_popen(monkeypatch, "claims_success_but_fails.ndjson", returncode=1)
    runner = AntigravityRunner(agy_path="agy")

    result = runner.run(
        task="Add a feature",
        repo=clean_git_repo,
        config=AgentRunConfig(model="gemini-2.5-pro"),
    )

    assert result.agent_report is not None
    assert result.agent_report.status == "success"
    assert result.process_exit_status == "failed"
    assert any("never treated as ground truth" in note for note in result.verification_notes)


# --- Git changed-file detection (deterministic evidence) ---------------------------


def test_git_evidence_detects_changed_new_and_deleted_files(clean_git_repo: Path) -> None:
    before = capture_git_state(clean_git_repo)

    (clean_git_repo / "README.md").write_text("# changed\n", encoding="utf-8")
    (clean_git_repo / "new_file.py").write_text("print('hi')\n", encoding="utf-8")

    after = capture_git_state(clean_git_repo)
    evidence = diff_git_evidence(clean_git_repo, before, after)

    assert "README.md" in evidence.changed_files
    assert "new_file.py" in evidence.added_files
    assert evidence.before_dirty is False
    assert evidence.after_dirty is True
    assert "README.md" in evidence.diff_stat


def test_git_evidence_detects_deleted_file(clean_git_repo: Path) -> None:
    before = capture_git_state(clean_git_repo)

    (clean_git_repo / "README.md").unlink()

    after = capture_git_state(clean_git_repo)
    evidence = diff_git_evidence(clean_git_repo, before, after)

    assert "README.md" in evidence.deleted_files
    assert "README.md" in evidence.changed_files


# --- spawn failure (agy invocation itself cannot start) -----------------------------


def test_spawn_failure_is_recorded_as_failed_run(
    monkeypatch: pytest.MonkeyPatch, clean_git_repo: Path
) -> None:
    def _raise(*args, **kwargs):
        raise OSError("no such file or directory: agy")

    monkeypatch.setattr("repoops.agent_runner._spawn_agy", _raise)
    runner = AntigravityRunner(agy_path="agy")

    result = runner.run(
        task="Add a feature",
        repo=clean_git_repo,
        config=AgentRunConfig(model="gemini-2.5-pro"),
    )

    assert result.process_status == "spawn_failed"
    assert result.process_exit_status == "failed"
    assert result.exit_code == -1


def test_agent_runner_emits_progress_events(
    monkeypatch: pytest.MonkeyPatch, clean_git_repo: Path
) -> None:
    _patch_popen(monkeypatch, "success.ndjson", returncode=0)
    runner = AntigravityRunner(agy_path="agy")

    logged: list[tuple[str, str]] = []
    result = runner.run(
        task="Add a feature",
        repo=clean_git_repo,
        config=AgentRunConfig(model="gemini-2.5-pro"),
        on_progress=lambda s, m: logged.append((s, m)),
    )

    assert result.exit_code == 0
    messages = [f"{s}: {m}" for s, m in logged]
    combined = "\n".join(messages)
    assert 'agent: started provider=antigravity model="gemini-2.5-pro"' in combined
    assert "agent: completed exit=0" in combined


def test_agent_runner_emits_spawn_failure_progress(
    monkeypatch: pytest.MonkeyPatch, clean_git_repo: Path
) -> None:
    def _raise(*args, **kwargs):
        raise OSError("no such file or directory: agy")

    monkeypatch.setattr("repoops.agent_runner._spawn_agy", _raise)
    runner = AntigravityRunner(agy_path="agy")

    logged: list[tuple[str, str]] = []
    result = runner.run(
        task="Add a feature",
        repo=clean_git_repo,
        config=AgentRunConfig(model="gemini-2.5-pro"),
        on_progress=lambda s, m: logged.append((s, m)),
    )

    assert result.process_status == "spawn_failed"
    messages = [f"{s}: {m}" for s, m in logged]
    combined = "\n".join(messages)
    assert "agent: process failure: no such file or directory: agy" in combined
