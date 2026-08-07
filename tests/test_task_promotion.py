"""Comprehensive unit tests for RepoOps integration branch promotion layer,

allowed path enforcement, dependency Git ancestry checking, and acceptance timeouts.
"""

import subprocess
import sys
from pathlib import Path

from repoops.acceptance import run_acceptance_commands
from repoops.agent_models import (
    AgentReport,
    AgentReportStatus,
    AgentRunConfig,
    AgentRunResult,
    GitEvidence,
    TaskContract,
)
from repoops.agent_runner import AgentRunner
from repoops.task_backlog import (
    INTEGRATION_BRANCH_NAME,
    TaskItem,
    check_eligibility,
    create_task_worktree,
    ensure_integration_branch,
    promote_task,
    run_next_task,
    save_task,
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


class MockPromotionRunner(AgentRunner):
    provider = "antigravity"

    def __init__(
        self,
        stub_result: AgentRunResult,
        files_to_create: dict[str, str] | None = None,
    ):
        self.stub_result = stub_result
        self.files_to_create = files_to_create or {}

    def run(self, *, task: str, repo: Path, config: AgentRunConfig) -> AgentRunResult:
        changed_files: list[str] = []
        for rel_path, content in self.files_to_create.items():
            target_path = repo / rel_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            changed_files.append(rel_path)

        run_dir = repo / ".repoops" / "agent-runs" / self.stub_result.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        res = self.stub_result.model_copy()
        if changed_files:
            res.git_evidence = GitEvidence(changed_files=changed_files, added_files=changed_files)
        res.run_dir = str(run_dir)
        (run_dir / "run.json").write_text(res.model_dump_json(indent=2), encoding="utf-8")
        return res


def test_1_integration_branch_initial_creation(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    baseline_sha = init_git_repo(repo_root)

    branch_name, int_head, origin_sha = ensure_integration_branch(repo_root)
    assert branch_name == INTEGRATION_BRANCH_NAME
    assert int_head == baseline_sha
    assert origin_sha == baseline_sha

    # Check git branch list
    proc_branch = subprocess.run(
        ["git", "branch"], cwd=repo_root, check=True, capture_output=True, text=True
    )
    assert INTEGRATION_BRANCH_NAME in proc_branch.stdout


def test_2_integration_branch_does_not_modify_user_branch(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    init_git_repo(repo_root)

    proc_orig_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    orig_branch = proc_orig_branch.stdout.strip()

    ensure_integration_branch(repo_root)

    proc_after_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc_after_branch.stdout.strip() == orig_branch


def test_3_4_task_001_verified_promoted_commit_created_and_head_advances(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    baseline_sha = init_git_repo(repo_root)

    t1 = TaskItem(
        id="task-001",
        status="ready",
        priority=10,
        objective="Create base file",
        allowed_paths=["base.txt"],
        acceptance=[f'{sys.executable} -c "import os; assert os.path.exists(\\\"base.txt\\\")"'],
    )
    save_task(repo_root, t1)

    stub = AgentRunResult(
        run_id="run_t1",
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
    runner = MockPromotionRunner(stub, files_to_create={"base.txt": "base ok"})

    outcome = run_next_task(repo_root, runner, AgentRunConfig(model="model"))
    assert outcome is not None
    task, result, _ = outcome

    assert task.status == "verified"
    assert task.promotion_status == "promoted"
    assert task.promoted_commit_sha is not None
    assert task.promoted_commit_sha != baseline_sha

    # Check integration HEAD
    _, int_head, _ = ensure_integration_branch(repo_root)
    assert int_head == task.promoted_commit_sha


def test_5_6_task_002_baseline_equals_promoted_task_001_and_sees_changes(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    init_git_repo(repo_root)

    # 1. Run TASK-001
    t1 = TaskItem(
        id="task-001",
        status="ready",
        priority=10,
        objective="Create base file",
        allowed_paths=["base.txt"],
        acceptance=[f'{sys.executable} -c "import os; assert os.path.exists(\\\"base.txt\\\")"'],
    )
    save_task(repo_root, t1)
    stub1 = AgentRunResult(
        run_id="run_t1",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
    )
    r1 = MockPromotionRunner(stub1, files_to_create={"base.txt": "base ok"})
    out1 = run_next_task(repo_root, r1, AgentRunConfig(model="model"))
    assert out1 is not None
    task1, _, _ = out1
    assert task1.status == "verified"

    # 2. Add TASK-002 depending on TASK-001
    t2 = TaskItem(
        id="task-002",
        status="ready",
        priority=20,
        depends_on=["task-001"],
        objective="Create derived file reading base.txt",
        allowed_paths=["derived.txt"],
        acceptance=[
            f'{sys.executable} -c "import os; '
            f'assert os.path.exists(\\\"base.txt\\\") and os.path.exists(\\\"derived.txt\\\")"'
        ],
    )
    save_task(repo_root, t2)

    stub2 = AgentRunResult(
        run_id="run_t2",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
    )
    r2 = MockPromotionRunner(stub2, files_to_create={"derived.txt": "derived ok"})
    out2 = run_next_task(repo_root, r2, AgentRunConfig(model="model"))
    assert out2 is not None
    task2, _, wt_path2 = out2

    assert task2.baseline_sha == task1.promoted_commit_sha
    assert task2.status == "verified"
    assert task2.promotion_status == "promoted"


def test_7_agent_cannot_control_commit_message(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    init_git_repo(repo_root)

    t1 = TaskItem(
        id="task-msg-test",
        status="ready",
        objective="Test commit msg",
        allowed_paths=["file.txt"],
        acceptance=[f'{sys.executable} -c "print(\\\"ok\\\")"'],
    )
    save_task(repo_root, t1)
    stub = AgentRunResult(
        run_id="run_msg",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
    )
    runner = MockPromotionRunner(stub, files_to_create={"file.txt": "content"})
    out = run_next_task(repo_root, runner, AgentRunConfig(model="model"))
    assert out is not None
    task, _, _ = out

    proc_log = subprocess.run(
        ["git", "log", "-1", "--pretty=format:%B", task.promoted_commit_sha],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    commit_msg = proc_log.stdout.strip()
    assert "repoops(task-msg-test): verified implementation" in commit_msg
    assert "Run-ID: run_msg" in commit_msg


def test_8_9_only_allowed_paths_staged_and_repoops_never_committed(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    init_git_repo(repo_root)

    wt_path, _ = create_task_worktree(repo_root, "task-boundary-test")
    (wt_path / "src").mkdir(parents=True)
    (wt_path / "src" / "ok.py").write_text("ok", encoding="utf-8")
    (wt_path / "unallowed.txt").write_text("bad", encoding="utf-8")

    task = TaskItem(
        id="task-boundary-test",
        objective="Test allowed paths",
        allowed_paths=["src/"],
    )
    result = AgentRunResult(
        run_id="run_b",
        provider="antigravity",
        requested_model="model",
        repository=str(wt_path),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        workspace_policy_status="passed",
        acceptance_status="passed",
        verdict="verified",
        git_evidence=GitEvidence(changed_files=["src/ok.py", "unallowed.txt"]),
    )

    prom_status, sha, err = promote_task(repo_root, task, result, wt_path)
    assert prom_status == "failed"
    assert sha is None
    assert "outside allowed_paths" in (err or "")


def test_10_promotion_failure_does_not_advance_integration_branch(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    initial_sha = init_git_repo(repo_root)

    wt_path, _ = create_task_worktree(repo_root, "task-fail-promo")
    (wt_path / ".repoops").mkdir(exist_ok=True)
    (wt_path / ".repoops" / "leak.txt").write_text("leak", encoding="utf-8")

    task = TaskItem(id="task-fail-promo", objective="Test leak", allowed_paths=[])
    result = AgentRunResult(
        run_id="run_leak",
        provider="antigravity",
        requested_model="model",
        repository=str(wt_path),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        workspace_policy_status="passed",
        acceptance_status="passed",
        verdict="verified",
        git_evidence=GitEvidence(changed_files=[".repoops/leak.txt"]),
    )

    prom_status, _, _ = promote_task(repo_root, task, result, wt_path)
    assert prom_status == "failed"

    _, current_int_sha, _ = ensure_integration_branch(repo_root)
    assert current_int_sha == initial_sha


def test_11_dependency_verified_status_without_promoted_commit_not_eligible(tmp_path):
    t1 = TaskItem(id="t1", status="verified", promotion_status="not_applicable", objective="Obj 1")
    t2 = TaskItem(id="t2", status="ready", depends_on=["t1"], objective="Obj 2")

    is_elig, reason = check_eligibility(t2, {"t1": t1, "t2": t2})
    assert is_elig is False
    assert "not promoted" in (reason or "")


def test_12_promoted_commit_must_be_ancestor_of_integration_head(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    init_git_repo(repo_root)

    fake_commit_sha = "0000000000000000000000000000000000000000"
    t1 = TaskItem(
        id="t1",
        status="verified",
        promotion_status="promoted",
        promoted_commit_sha=fake_commit_sha,
        objective="Obj 1",
    )
    t2 = TaskItem(id="t2", status="ready", depends_on=["t1"], objective="Obj 2")

    is_elig, reason = check_eligibility(t2, {"t1": t1, "t2": t2}, repo_root=repo_root)
    assert is_elig is False
    assert "not an ancestor" in (reason or "")


def test_13_acceptance_timeout_produces_failed_verification(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # Run command that sleeps longer than timeout
    if sys.platform == "win32":
        cmd = 'powershell -Command "Start-Sleep -Seconds 10"'
    else:
        cmd = "sleep 10"

    contract = TaskContract(
        id="t_timeout",
        objective="Test timeout",
        acceptance=[cmd],
    )

    status, results = run_acceptance_commands(contract, repo_root, timeout_seconds=1)
    assert status == "failed"
    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].timed_out is True


def test_14_attempt_count_increments_once_per_execution_attempt(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    init_git_repo(repo_root)

    t1 = TaskItem(
        id="task-attempt",
        status="ready",
        priority=10,
        objective="Attempt test",
        allowed_paths=["attempt.txt"],
        acceptance=[f'{sys.executable} -c "print(\\\"ok\\\")"'],
    )
    save_task(repo_root, t1)
    stub = AgentRunResult(
        run_id="run_att",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
    )
    runner = MockPromotionRunner(stub, files_to_create={"attempt.txt": "ok"})

    outcome = run_next_task(repo_root, runner, AgentRunConfig(model="model"))
    assert outcome is not None
    task, _, _ = outcome
    assert task.attempt_count == 1
    assert task.last_attempt_at is not None


def test_15_16_failed_and_policy_violation_tasks_not_promoted(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    initial_sha = init_git_repo(repo_root)

    t1 = TaskItem(
        id="task-failed-no-promo",
        status="ready",
        objective="Will fail acceptance",
        allowed_paths=["f.txt"],
        acceptance=[f'{sys.executable} -c "import sys; sys.exit(1)"'],
    )
    save_task(repo_root, t1)

    stub = AgentRunResult(
        run_id="run_f",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
    )
    runner = MockPromotionRunner(stub, files_to_create={"f.txt": "content"})

    outcome = run_next_task(repo_root, runner, AgentRunConfig(model="model"))
    assert outcome is not None
    task, result, _ = outcome

    assert task.status == "failed"
    assert task.promotion_status == "not_applicable"
    assert task.promoted_commit_sha is None

    _, current_sha, _ = ensure_integration_branch(repo_root)
    assert current_sha == initial_sha
