"""Comprehensive unit tests for TaskBacklog, deterministic selection,
locking, and Git worktree isolation.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from repoops.agent_models import (
    AgentReport,
    AgentReportStatus,
    AgentRunConfig,
    AgentRunResult,
    ExpectedChanges,
    GitEvidence,
)
from repoops.agent_runner import AgentRunner
from repoops.task_backlog import (
    TaskItem,
    TaskLock,
    TaskLockedError,
    check_eligibility,
    create_task_worktree,
    load_backlog,
    run_next_task,
    save_task,
    select_next_task,
)


def init_git_repo(path: Path) -> str:
    """Initialize a git repo at path with an initial commit and return baseline SHA."""
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


class MockBacklogRunner(AgentRunner):
    provider = "antigravity"

    def __init__(self, stub_result: AgentRunResult, mutates_worktree: bool = True):
        self.stub_result = stub_result
        self.mutates_worktree = mutates_worktree

    def run(self, *, task: str, repo: Path, config: AgentRunConfig) -> AgentRunResult:
        if self.mutates_worktree:
            # Simulate real file modification inside the worktree
            new_file = repo / "worktree_file.txt"
            new_file.write_text("modified in worktree", encoding="utf-8")
            git_ev = GitEvidence(changed_files=["worktree_file.txt"])
        else:
            git_ev = GitEvidence(changed_files=[])

        run_dir = repo / ".repoops" / "agent-runs" / self.stub_result.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        res = self.stub_result.model_copy()
        res.git_evidence = git_ev
        res.run_dir = str(run_dir)
        (run_dir / "run.json").write_text(res.model_dump_json(indent=2), encoding="utf-8")
        return res


def test_1_backlog_task_loading(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tasks_dir = repo / ".repoops" / "tasks"
    tasks_dir.mkdir(parents=True)

    t1 = TaskItem(id="task-001", objective="Obj 1", priority=10)
    t2 = TaskItem(id="task-002", objective="Obj 2", priority=20)
    save_task(repo, t1)
    save_task(repo, t2)

    loaded = load_backlog(repo)
    assert len(loaded) == 2
    ids = [t.id for t in loaded]
    assert "task-001" in ids
    assert "task-002" in ids


def test_2_deterministic_priority_ordering(tmp_path):
    t_low = TaskItem(id="task-low", priority=30, objective="Low pri")
    t_high = TaskItem(id="task-high", priority=10, objective="High pri")
    t_mid = TaskItem(id="task-mid", priority=20, objective="Mid pri")

    backlog = [t_low, t_high, t_mid]
    selected = select_next_task(backlog)
    assert selected is not None
    assert selected.id == "task-high"


def test_3_lexical_tie_breaking(tmp_path):
    t_c = TaskItem(id="task-c", priority=10, objective="Obj C")
    t_b = TaskItem(id="task-b", priority=10, objective="Obj B")
    t_a = TaskItem(id="task-a", priority=20, objective="Obj A")

    backlog = [t_c, t_b, t_a]
    selected = select_next_task(backlog)
    assert selected is not None
    # priority 10 < priority 20; tie between task-b & task-c resolved lexicographically
    assert selected.id == "task-b"


def test_4_dependency_satisfied_eligible(tmp_path):
    t1 = TaskItem(
        id="task-001",
        status="verified",
        promotion_status="promoted",
        promoted_commit_sha="dummy_sha",
        objective="Done",
    )
    t2 = TaskItem(id="task-002", status="ready", depends_on=["task-001"], objective="Next")

    backlog = [t1, t2]
    selected = select_next_task(backlog)
    assert selected is not None
    assert selected.id == "task-002"


def test_5_dependency_not_verified_not_eligible(tmp_path):
    t1 = TaskItem(id="task-001", status="failed", objective="Failed dep")
    t2 = TaskItem(id="task-002", status="ready", depends_on=["task-001"], objective="Blocked task")

    backlog = [t1, t2]
    selected = select_next_task(backlog)
    assert selected is None


def test_6_missing_dependency_handling(tmp_path):
    t2 = TaskItem(
        id="task-002",
        status="ready",
        depends_on=["task-missing"],
        objective="Missing dep task",
    )

    backlog = [t2]
    map_backlog = {t.id: t for t in backlog}
    is_elig, reason = check_eligibility(t2, map_backlog)
    assert is_elig is False
    assert "does not exist in backlog" in (reason or "")
    assert select_next_task(backlog) is None


def test_7_no_eligible_tasks(tmp_path):
    t1 = TaskItem(id="task-001", status="verified", objective="Done")
    t2 = TaskItem(id="task-002", status="failed", objective="Failed")

    assert select_next_task([t1, t2]) is None


def test_8_same_backlog_same_selected_task(tmp_path):
    t1 = TaskItem(id="task-b", priority=10, objective="B")
    t2 = TaskItem(id="task-c", priority=10, objective="C")
    t3 = TaskItem(id="task-a", priority=20, objective="A")

    b1 = [t1, t2, t3]
    b2 = [t3, t2, t1]
    assert select_next_task(b1).id == select_next_task(b2).id == "task-b"


def test_9_10_ready_running_verified_and_failed(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    init_git_repo(repo_root)

    t1 = TaskItem(
        id="task-v",
        status="ready",
        priority=10,
        objective="Verify task",
        acceptance=[f'{sys.executable} -c "print(\\"ok\\")"'],
    )
    save_task(repo_root, t1)

    stub_success = AgentRunResult(
        run_id="run_v1",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        agent_report=AgentReport(status=AgentReportStatus.SUCCESS, summary="Done"),
    )
    runner_success = MockBacklogRunner(stub_success, mutates_worktree=True)

    outcome = run_next_task(repo_root, runner_success, AgentRunConfig(model="model"))
    assert outcome is not None
    task, result, wt_path = outcome
    assert task.status == "verified"
    assert result.verdict == "verified"

    # Test failure path
    t2 = TaskItem(
        id="task-f",
        status="ready",
        priority=20,
        objective="Fail task",
        acceptance=[f'{sys.executable} -c "import sys; sys.exit(1)"'],
    )
    save_task(repo_root, t2)

    stub_fail = AgentRunResult(
        run_id="run_f1",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
    )
    runner_fail = MockBacklogRunner(stub_fail, mutates_worktree=True)

    outcome_f = run_next_task(repo_root, runner_fail, AgentRunConfig(model="model"))
    assert outcome_f is not None
    task_f, result_f, _ = outcome_f
    assert task_f.status == "failed"
    assert result_f.verdict == "failed"


def test_11_run_id_persisted_on_task(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    init_git_repo(repo_root)

    t = TaskItem(
        id="task-run-persisted",
        status="ready",
        objective="Check run id",
        acceptance=[f'{sys.executable} -c "print(\\"ok\\")"'],
    )
    save_task(repo_root, t)

    stub = AgentRunResult(
        run_id="run_12345",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
    )
    runner = MockBacklogRunner(stub, mutates_worktree=True)

    outcome = run_next_task(repo_root, runner, AgentRunConfig(model="model"))
    assert outcome is not None
    task, result, _ = outcome
    assert task.last_run_id == "run_12345"

    # Reload from disk
    loaded_tasks = load_backlog(repo_root)
    saved_task = next(item for item in loaded_tasks if item.id == "task-run-persisted")
    assert saved_task.last_run_id == "run_12345"
    assert saved_task.status == "verified"


def test_12_second_concurrent_launch_rejected(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    with TaskLock(repo_root, "task-concurrent"), pytest.raises(TaskLockedError):
        TaskLock(repo_root, "task-concurrent").acquire()


def test_13_worktree_created_from_expected_baseline_sha(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    baseline_sha = init_git_repo(repo_root)

    wt_path, sha = create_task_worktree(repo_root, "task-wt-test")
    assert sha == baseline_sha
    assert wt_path.exists()
    assert wt_path.is_dir()

    # Check worktree HEAD SHA
    proc_wt_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=wt_path, check=True, capture_output=True, text=True
    )
    assert proc_wt_head.stdout.strip() == baseline_sha


def test_14_primary_working_tree_remains_untouched(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    init_git_repo(repo_root)

    t = TaskItem(
        id="task-untouched-primary",
        status="ready",
        objective="Mutate worktree",
        acceptance=[f'{sys.executable} -c "print(\\"ok\\")"'],
    )
    save_task(repo_root, t)

    stub = AgentRunResult(
        run_id="run_wt_mod",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
    )
    runner = MockBacklogRunner(stub, mutates_worktree=True)

    outcome = run_next_task(repo_root, runner, AgentRunConfig(model="model"))
    assert outcome is not None
    task, result, wt_path = outcome

    # Task was verified and promoted to repoops/integration
    assert task.status == "verified"
    assert task.promotion_status == "promoted"

    # Integration branch contains the file
    proc_ls = subprocess.run(
        ["git", "ls-tree", "--name-only", "repoops/integration"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "worktree_file.txt" in proc_ls.stdout

    # Primary working tree DOES NOT contain the file
    assert not (repo_root / "worktree_file.txt").exists()

    # Primary status porcelain shows zero user code mutations
    proc_stat = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    code_changes = [line for line in proc_stat.stdout.splitlines() if "worktree_file.txt" in line]
    assert len(code_changes) == 0


def test_15_required_changes_missing_failed_not_policy_violation(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    init_git_repo(repo_root)

    t = TaskItem(
        id="task-no-changes",
        status="ready",
        objective="Required changes missing",
        expected_changes=ExpectedChanges(required=True),
        acceptance=[f'{sys.executable} -c "print(\\"ok\\")"'],
    )
    save_task(repo_root, t)

    stub = AgentRunResult(
        run_id="run_no_changes",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
    )
    # Runner that mutates NOTHING in worktree
    runner = MockBacklogRunner(stub, mutates_worktree=False)

    outcome = run_next_task(repo_root, runner, AgentRunConfig(model="model"))
    assert outcome is not None
    task, result, _ = outcome

    assert result.verdict == "failed"
    assert result.workspace_policy_status == "passed"
    assert task.status == "failed"
    assert any("zero Git changes were detected" in note for note in result.verification_notes)
