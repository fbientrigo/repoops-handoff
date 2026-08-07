"""Integration unit tests for run_verified_task and 4-tier verdict derivation."""

import sys
from pathlib import Path

from repoops.agent_models import (
    AgentReport,
    AgentReportStatus,
    AgentRunConfig,
    AgentRunResult,
    ExpectedChanges,
    GitEvidence,
    TaskContract,
    ToolStep,
)
from repoops.agent_runner import AgentRunner
from repoops.agent_verification import run_verified_task


class MockRunner(AgentRunner):
    provider = "antigravity"

    def __init__(self, stub_result: AgentRunResult):
        self.stub_result = stub_result
        self.last_prompt: str | None = None

    def run(self, *, task: str, repo: Path, config: AgentRunConfig) -> AgentRunResult:
        self.last_prompt = task
        # Make a copy of stub_result for persistence simulation
        run_dir = repo / ".repoops" / "agent-runs" / self.stub_result.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        res = self.stub_result.model_copy()
        res.run_dir = str(run_dir)
        (run_dir / "run.json").write_text(res.model_dump_json(indent=2), encoding="utf-8")
        return res


def test_verified_success(tmp_path):
    # Required change + actual git change + acceptance passes -> verified
    stub = AgentRunResult(
        run_id="run_verified",
        provider="antigravity",
        requested_model="model",
        repository=str(tmp_path),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        agent_report=AgentReport(status=AgentReportStatus.SUCCESS, summary="Done"),
        git_evidence=GitEvidence(changed_files=["src/main.py"]),
    )
    runner = MockRunner(stub)
    contract = TaskContract(
        id="t_verified",
        objective="Modify main.py",
        expected_changes=ExpectedChanges(required=True),
        allowed_paths=["src/"],
        acceptance=[f'{sys.executable} -c "print(\\\"ok\\\")"'],
    )

    result = run_verified_task(runner, contract, tmp_path, AgentRunConfig(model="model"))
    assert result.verdict == "verified"
    assert result.workspace_policy_status == "passed"
    assert result.acceptance_status == "passed"


def test_required_change_with_zero_git_changes_fails(tmp_path):
    # Required change + zero Git changes -> policy_violation or failed
    stub = AgentRunResult(
        run_id="run_zero_git",
        provider="antigravity",
        requested_model="model",
        repository=str(tmp_path),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        agent_report=AgentReport(status=AgentReportStatus.SUCCESS, summary="Claims success"),
        git_evidence=GitEvidence(changed_files=[]),
    )
    runner = MockRunner(stub)
    contract = TaskContract(
        id="t_zero",
        objective="Modify main.py",
        expected_changes=ExpectedChanges(required=True),
        allowed_paths=["src/"],
        acceptance=[f'{sys.executable} -c "print(\\\"ok\\\")"'],
    )

    result = run_verified_task(runner, contract, tmp_path, AgentRunConfig(model="model"))
    assert result.verdict == "failed"
    assert result.workspace_policy_status == "passed"


def test_agent_reports_success_but_zero_git_changes_not_verified(tmp_path):
    # Agent says success + zero Git changes -> not verified
    stub = AgentRunResult(
        run_id="run_agent_claim",
        provider="antigravity",
        requested_model="model",
        repository=str(tmp_path),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        agent_report=AgentReport(status=AgentReportStatus.SUCCESS, summary="I fixed it!"),
        git_evidence=GitEvidence(changed_files=[]),
    )
    runner = MockRunner(stub)
    contract = TaskContract(
        id="t_agent_claim",
        objective="Fix bug",
        expected_changes=ExpectedChanges(required=True),
        acceptance=[f'{sys.executable} -c "print(\\\"ok\\\")"'],
    )

    result = run_verified_task(runner, contract, tmp_path, AgentRunConfig(model="model"))
    assert result.verdict != "verified"


def test_git_change_outside_allowed_paths_is_policy_violation(tmp_path):
    # Git change outside allowed_paths -> policy_violation
    stub = AgentRunResult(
        run_id="run_unallowed_git",
        provider="antigravity",
        requested_model="model",
        repository=str(tmp_path),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        git_evidence=GitEvidence(changed_files=["outside/secret.py"]),
    )
    runner = MockRunner(stub)
    contract = TaskContract(
        id="t_unallowed",
        objective="Fix bug",
        allowed_paths=["src/"],
        acceptance=[f'{sys.executable} -c "print(\\\"ok\\\")"'],
    )

    result = run_verified_task(runner, contract, tmp_path, AgentRunConfig(model="model"))
    assert result.verdict == "policy_violation"
    assert result.workspace_policy_status == "violation"


def test_observable_tool_outside_repo_is_policy_violation(tmp_path):
    # Observable file tool targeting outside repo -> policy_violation
    outside_file = str((tmp_path.parent / "leak.txt").resolve())
    step = ToolStep(
        index=0,
        type="step_update",
        tool="write_to_file",
        raw={
            "step_update": {
                "tool_info": {
                    "name": "write_to_file",
                    "parameters": {"TargetFile": outside_file},
                }
            }
        },
    )
    stub = AgentRunResult(
        run_id="run_tool_leak",
        provider="antigravity",
        requested_model="model",
        repository=str(tmp_path),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        steps=[step],
        git_evidence=GitEvidence(changed_files=["src/main.py"]),
    )
    runner = MockRunner(stub)
    contract = TaskContract(
        id="t_tool_leak",
        objective="Fix bug",
        allowed_paths=["src/"],
        acceptance=[f'{sys.executable} -c "print(\\\"ok\\\")"'],
    )

    result = run_verified_task(runner, contract, tmp_path, AgentRunConfig(model="model"))
    assert result.verdict == "policy_violation"


def test_acceptance_failure_results_in_failed_verdict(tmp_path):
    # Acceptance command failure -> failed
    stub = AgentRunResult(
        run_id="run_acc_fail",
        provider="antigravity",
        requested_model="model",
        repository=str(tmp_path),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        git_evidence=GitEvidence(changed_files=["src/main.py"]),
    )
    runner = MockRunner(stub)
    contract = TaskContract(
        id="t_acc_fail",
        objective="Fix bug",
        allowed_paths=["src/"],
        acceptance=[f'{sys.executable} -c "import sys; sys.exit(1)"'],
    )

    result = run_verified_task(runner, contract, tmp_path, AgentRunConfig(model="model"))
    assert result.verdict == "failed"
    assert result.acceptance_status == "failed"


def test_agent_subprocess_failure_results_in_failed_verdict(tmp_path):
    # Agent subprocess failure -> failed
    stub = AgentRunResult(
        run_id="run_proc_fail",
        provider="antigravity",
        requested_model="model",
        repository=str(tmp_path),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=1,
        process_status="completed",
        process_exit_status="failed",
        git_evidence=GitEvidence(changed_files=["src/main.py"]),
    )
    runner = MockRunner(stub)
    contract = TaskContract(
        id="t_proc_fail",
        objective="Fix bug",
        allowed_paths=["src/"],
        acceptance=[f'{sys.executable} -c "print(\\\"ok\\\")"'],
    )

    result = run_verified_task(runner, contract, tmp_path, AgentRunConfig(model="model"))
    assert result.verdict == "failed"
    assert result.acceptance_status == "skipped"


def test_unverified_verdict_when_no_acceptance_commands(tmp_path):
    # Process succeeded + policy passed + git changes present + no acceptance commands -> unverified
    stub = AgentRunResult(
        run_id="run_no_acc",
        provider="antigravity",
        requested_model="model",
        repository=str(tmp_path),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        git_evidence=GitEvidence(changed_files=["src/main.py"]),
    )
    runner = MockRunner(stub)
    contract = TaskContract(
        id="t_no_acc",
        objective="Fix bug",
        allowed_paths=["src/"],
        acceptance=[],
    )

    result = run_verified_task(runner, contract, tmp_path, AgentRunConfig(model="model"))
    assert result.verdict == "unverified"
    assert result.acceptance_status == "skipped"
