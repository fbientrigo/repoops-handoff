"""Comprehensive tests for RepoOps single-run unattended scheduler."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from repoops.agent_models import (
    AgentReport,
    AgentReportStatus,
    AgentRunConfig,
    AgentRunResult,
    GitEvidence,
)
from repoops.agent_runner import AgentRunner, AntigravityRunner
from repoops.scheduler import run_scheduler_once
from repoops.task_backlog import (
    SchedulerLock,
    TaskItem,
    ensure_integration_branch,
    load_backlog,
    save_task,
)


def init_git_repo(path: Path) -> str:
    """Initialize a git repo at path with initial commit and return baseline SHA."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "TestUser"], cwd=path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    init_file = path / "README.md"
    init_file.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=path, check=True, capture_output=True
    )
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


class MockSchedulerRunner(AgentRunner):
    provider = "antigravity"

    def __init__(
        self,
        process_exit_status: str = "success",
        verdict: str = "verified",
        mutates_worktree: bool = True,
        created_file: str = "created.txt",
    ):
        self.process_exit_status = process_exit_status
        self.verdict = verdict
        self.mutates_worktree = mutates_worktree
        self.created_file = created_file
        self.run_count = 0

    def run(self, *, task: str, repo: Path, config: AgentRunConfig) -> AgentRunResult:
        self.run_count += 1
        run_id = f"mock-run-{self.run_count}"

        if self.mutates_worktree:
            fpath = repo / self.created_file
            fpath.write_text("content", encoding="utf-8")
            git_ev = GitEvidence(changed_files=[], added_files=[self.created_file])
        else:
            git_ev = GitEvidence()

        agent_report = (
            AgentReport(status=AgentReportStatus.SUCCESS, summary="Mock success")
            if self.process_exit_status == "success"
            else None
        )

        res = AgentRunResult(
            run_id=run_id,
            provider=self.provider,
            requested_model=config.model,
            resolved_model=config.model,
            session_id="mock-session",
            repository=str(repo),
            started_at="2026-08-07T00:00:00Z",
            ended_at="2026-08-07T00:00:01Z",
            exit_code=0 if self.process_exit_status == "success" else 1,
            process_status="completed",
            process_exit_status=self.process_exit_status,
            agent_report=agent_report,
            git_evidence=git_ev,
            verdict=self.verdict,
            workspace_policy_status="passed" if self.verdict != "policy_violation" else "violation",
            acceptance_status="passed" if self.verdict == "verified" else "skipped",
        )
        run_dir = repo / ".repoops" / "agent-runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        res.run_dir = str(run_dir)
        (run_dir / "run.json").write_text(res.model_dump_json(indent=2), encoding="utf-8")
        return res


def patch_runner(monkeypatch: pytest.MonkeyPatch, mock_runner: AgentRunner) -> None:
    monkeypatch.setattr("repoops.scheduler.select_runner", lambda p: mock_runner)


# 1. no eligible task -> success/no-op
def test_no_eligible_task_returns_no_op(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    mock_runner = MockSchedulerRunner()
    patch_runner(monkeypatch, mock_runner)

    res = run_scheduler_once(repo, model="test-model")

    assert res.outcome == "no_eligible_task"
    assert res.selected_task_id is None
    assert mock_runner.run_count == 0
    assert Path(res.run_dir).exists()


# 2. one eligible task -> exactly one task executed
def test_one_eligible_task_executes_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    t1 = TaskItem(
        id="task-001",
        objective="Do task 1",
        status="ready",
        acceptance=['python -c "print(\'ok\')"'],
    )
    save_task(repo, t1)

    mock_runner = MockSchedulerRunner()
    patch_runner(monkeypatch, mock_runner)

    res = run_scheduler_once(repo, model="test-model")

    assert res.outcome == "task_verified"
    assert res.selected_task_id == "task-001"
    assert mock_runner.run_count == 1
    assert res.promoted_commit_sha is not None


# 3. two eligible tasks -> only highest-priority task executes
def test_two_eligible_tasks_executes_highest_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    t1 = TaskItem(
        id="task-low",
        objective="Low priority",
        priority=50,
        status="ready",
        acceptance=['python -c "print(\'ok\')"'],
    )
    t2 = TaskItem(
        id="task-high",
        objective="High priority",
        priority=10,
        status="ready",
        acceptance=['python -c "print(\'ok\')"'],
    )
    save_task(repo, t1)
    save_task(repo, t2)

    mock_runner = MockSchedulerRunner()
    patch_runner(monkeypatch, mock_runner)

    res = run_scheduler_once(repo, model="test-model")

    assert res.outcome == "task_verified"
    assert res.selected_task_id == "task-high"
    assert mock_runner.run_count == 1

    # Check low priority task remains ready and unexecuted
    backlog = load_backlog(repo)
    low_task = next(t for t in backlog if t.id == "task-low")
    assert low_task.status == "ready"
    assert low_task.attempt_count == 0


# 4. successful task -> scheduler returns task_verified
def test_successful_task_returns_task_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    t1 = TaskItem(
        id="task-001",
        objective="Task 1",
        status="ready",
        acceptance=['python -c "print(\'ok\')"'],
    )
    save_task(repo, t1)

    mock_runner = MockSchedulerRunner(verdict="verified")
    patch_runner(monkeypatch, mock_runner)

    res = run_scheduler_once(repo, model="test-model")

    assert res.outcome == "task_verified"
    assert res.task_verdict == "verified"


# 5. failed task -> scheduler stops
def test_failed_task_stops_scheduler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    t1 = TaskItem(id="task-001", objective="Task 1", status="ready")
    save_task(repo, t1)

    mock_runner = MockSchedulerRunner(
        process_exit_status="failed", verdict="failed", mutates_worktree=False
    )
    patch_runner(monkeypatch, mock_runner)

    res = run_scheduler_once(repo, model="test-model")

    assert res.outcome == "task_failed"
    assert res.task_verdict == "failed"
    assert mock_runner.run_count == 1

    backlog = load_backlog(repo)
    t_after = next(t for t in backlog if t.id == "task-001")
    assert t_after.status == "failed"
    assert t_after.attempt_count == 1


# 6. policy violation -> scheduler stops
def test_policy_violation_stops_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    t1 = TaskItem(
        id="task-001",
        objective="Task 1",
        status="ready",
        allowed_paths=["allowed.txt"],
        acceptance=['python -c "print(\'ok\')"'],
    )
    save_task(repo, t1)

    mock_runner = MockSchedulerRunner(
        process_exit_status="success",
        verdict="policy_violation",
        created_file="created.txt",
    )
    patch_runner(monkeypatch, mock_runner)

    res = run_scheduler_once(repo, model="test-model")

    assert res.outcome == "task_policy_violation"
    assert res.task_verdict == "policy_violation"


# 7. unverified -> scheduler stops
def test_unverified_task_stops_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    # acceptance is empty -> unverified
    t1 = TaskItem(id="task-001", objective="Task 1", status="ready", acceptance=[])
    save_task(repo, t1)

    mock_runner = MockSchedulerRunner(process_exit_status="success", verdict="unverified")
    patch_runner(monkeypatch, mock_runner)

    res = run_scheduler_once(repo, model="test-model")

    assert res.outcome == "task_unverified"
    assert res.task_verdict == "unverified"


# 8. no automatic retry occurs
def test_no_automatic_retry_occurs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    t1 = TaskItem(id="task-001", objective="Task 1", status="ready")
    save_task(repo, t1)

    mock_runner = MockSchedulerRunner(
        process_exit_status="failed", verdict="failed", mutates_worktree=False
    )
    patch_runner(monkeypatch, mock_runner)

    # First run fails
    res1 = run_scheduler_once(repo, model="test-model")
    assert res1.outcome == "task_failed"

    # Second invocation should see no eligible task (task-001 is now status=failed)
    res2 = run_scheduler_once(repo, model="test-model")
    assert res2.outcome == "no_eligible_task"
    assert mock_runner.run_count == 1  # No second agent run was triggered


# 9. max_attempts prevents re-execution even if status is ready
def test_max_attempts_prevents_reexecution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    # Task has attempt_count=1 and status="ready"
    t1 = TaskItem(id="task-001", objective="Task 1", status="ready", attempt_count=1)
    save_task(repo, t1)

    mock_runner = MockSchedulerRunner()
    patch_runner(monkeypatch, mock_runner)

    res = run_scheduler_once(repo, model="test-model", max_attempts=1)

    assert res.outcome == "no_eligible_task"
    assert mock_runner.run_count == 0


# 10. scheduler-level concurrent invocation rejected
def test_concurrent_scheduler_invocation_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    # Acquire lock manually
    lock = SchedulerLock(repo)
    lock.acquire()

    try:
        res = run_scheduler_once(repo, model="test-model")
        assert res.outcome == "locked"
        assert "locked by active process" in res.reason
    finally:
        lock.release()


# 11. stale scheduler lock handled safely
def test_stale_scheduler_lock_handled_safely(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    # Write stale lock with inactive PID 999999
    locks_dir = repo / ".repoops" / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    stale_lock = locks_dir / "scheduler.lock"
    stale_lock.write_text(json.dumps({"pid": 999999, "acquired_at": "old"}), encoding="utf-8")

    res = run_scheduler_once(repo, model="test-model")

    # Stale lock cleared automatically, returns no_eligible_task
    assert res.outcome == "no_eligible_task"


# 12 & 13. agy overall timeout -> task failure, no promotion & timeout evidence persisted
class TimeoutFakePopen:
    def __init__(self) -> None:
        self.stdout = iter(['{"event":"init","init":{"model":"gemini"}}\n'])
        self.stderr = None
        self._returncode = None

    def wait(self, timeout: float | None = None) -> int:
        raise subprocess.TimeoutExpired(cmd="agy", timeout=timeout or 0)

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


def test_agy_overall_timeout_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    monkeypatch.setattr(
        "repoops.agent_runner._spawn_agy",
        lambda *a, **k: TimeoutFakePopen(),
    )

    runner = AntigravityRunner(agy_path="agy")
    config = AgentRunConfig(model="gemini", timeout_seconds=1)

    result = runner.run(task="Timeout task", repo=repo, config=config)

    assert result.process_status == "timed_out"
    assert result.process_exit_status == "failed"
    assert result.exit_code == -1
    assert "timed out after 1 seconds" in result.verification_notes[0]

    # Verify run record persisted evidence
    run_dir = Path(result.run_dir)
    assert (run_dir / "run.json").exists()
    assert (run_dir / "stream.ndjson").exists()


# 14. integration branch only advances on verified promotion
def test_integration_branch_only_advances_on_verified_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    _, int_head_before, _ = ensure_integration_branch(repo)

    t1 = TaskItem(id="task-failing", objective="Will fail", status="ready")
    save_task(repo, t1)

    mock_runner = MockSchedulerRunner(
        process_exit_status="failed", verdict="failed", mutates_worktree=False
    )
    patch_runner(monkeypatch, mock_runner)

    res = run_scheduler_once(repo, model="test-model")

    assert res.outcome == "task_failed"
    assert res.integration_head_before == int_head_before
    assert res.integration_head_after == int_head_before
    assert res.promoted_commit_sha is None


# 15. second task remains untouched after first scheduler invocation
def test_second_task_remains_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    t1 = TaskItem(
        id="task-001",
        objective="First task",
        priority=10,
        status="ready",
        acceptance=['python -c "print(\'ok\')"'],
    )
    t2 = TaskItem(
        id="task-002",
        objective="Second task",
        priority=20,
        depends_on=["task-001"],
        status="ready",
        acceptance=['python -c "print(\'ok\')"'],
    )
    save_task(repo, t1)
    save_task(repo, t2)

    mock_runner = MockSchedulerRunner()
    patch_runner(monkeypatch, mock_runner)

    res = run_scheduler_once(repo, model="test-model")

    assert res.outcome == "task_verified"
    assert res.selected_task_id == "task-001"

    # Check task-002 is completely untouched
    backlog = load_backlog(repo)
    task2_after = next(t for t in backlog if t.id == "task-002")
    assert task2_after.status == "ready"
    assert task2_after.attempt_count == 0
    assert task2_after.promotion_status == "not_applicable"
