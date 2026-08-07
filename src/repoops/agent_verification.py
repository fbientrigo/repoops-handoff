"""Verification layer orchestrator for repoops agent execution."""

from __future__ import annotations

from pathlib import Path

from repoops.acceptance import run_acceptance_commands
from repoops.agent_models import AgentRunConfig, AgentRunResult, TaskContract
from repoops.agent_runner import AgentRunner
from repoops.task_contract import build_task_prompt
from repoops.workspace_guard import inspect_workspace_policy


def derive_repoops_verdict(
    *,
    process_exit_status: str,
    workspace_policy_status: str,
    acceptance_status: str,
    expected_changes_required: bool,
    actual_git_changes_count: int,
) -> str:
    """Derive one authoritative RepoOps verdict.

    Returns one of: "verified", "failed", "policy_violation", "unverified".
    """
    if process_exit_status != "success":
        return "failed"

    if workspace_policy_status == "violation":
        return "policy_violation"

    if expected_changes_required and actual_git_changes_count == 0:
        return "failed"

    if acceptance_status == "failed":
        return "failed"

    if acceptance_status == "skipped":
        return "unverified"

    if acceptance_status == "passed":
        return "verified"

    return "unverified"


def run_verified_task(
    runner: AgentRunner,
    contract: TaskContract,
    repo: Path,
    config: AgentRunConfig,
) -> AgentRunResult:
    """Execute a task contract through an AgentRunner and verify results deterministically."""
    repo_root = Path(repo).expanduser().resolve()
    prompt = build_task_prompt(contract, repo_root)

    # 1. Execute agent subprocess
    result = runner.run(task=prompt, repo=repo_root, config=config)
    result.task_contract = contract

    # 2. Workspace boundary & path verification
    ws_status, ws_violations = inspect_workspace_policy(contract, result, repo_root)
    result.workspace_policy_status = ws_status
    result.workspace_policy_violations = ws_violations

    # 3. Deterministic acceptance commands execution (if process succeeded & policy passed)
    git = result.git_evidence
    actual_git_changes_count = (
        len(git.changed_files) + len(git.added_files) + len(git.deleted_files)
    )

    if result.process_exit_status == "success" and ws_status == "passed":
        acc_status, acc_results = run_acceptance_commands(contract, repo_root)
    else:
        acc_status, acc_results = "skipped", []

    result.acceptance_status = acc_status
    result.acceptance_results = acc_results

    if contract.expected_changes.required and actual_git_changes_count == 0:
        result.verification_notes.append(
            "TaskContract expected_changes.required is True, but zero Git changes were detected."
        )

    # 4. Final RepoOps verdict derivation
    result.verdict = derive_repoops_verdict(
        process_exit_status=result.process_exit_status,
        workspace_policy_status=ws_status,
        acceptance_status=acc_status,
        expected_changes_required=contract.expected_changes.required,
        actual_git_changes_count=actual_git_changes_count,
    )

    # 5. Re-persist updated run record
    if result.run_dir:
        run_json_path = Path(result.run_dir) / "run.json"
        run_json_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")

    return result
