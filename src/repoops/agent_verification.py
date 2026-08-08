"""Verification layer orchestrator for repoops agent execution."""

from __future__ import annotations

import inspect
from pathlib import Path

from repoops.acceptance import run_acceptance_commands
from repoops.agent_models import AgentRunConfig, AgentRunResult, TaskContract
from repoops.agent_runner import AgentRunner
from repoops.progress import ProgressCallback
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
    on_progress: ProgressCallback | None = None,
) -> AgentRunResult:
    """Execute a task contract through an AgentRunner and verify results deterministically."""
    repo_root = Path(repo).expanduser().resolve()
    prompt = build_task_prompt(contract, repo_root)

    # 1. Execute agent subprocess
    sig = inspect.signature(runner.run)
    if "on_progress" in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    ):
        result = runner.run(task=prompt, repo=repo_root, config=config, on_progress=on_progress)
    else:
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

    if on_progress:
        suffix = "s" if actual_git_changes_count != 1 else ""
        on_progress("verify", f"git changes detected: {actual_git_changes_count} file{suffix}")
        if ws_status != "passed":
            for v in ws_violations:
                on_progress("verify", f"policy violation: {v}")
        if contract.expected_changes.required and actual_git_changes_count == 0:
            on_progress(
                "verify", "policy violation: expected changes required but 0 Git changes detected"
            )

    if result.process_exit_status == "success" and ws_status == "passed":
        acc_status, acc_results = run_acceptance_commands(
            contract, repo_root, on_progress=on_progress
        )
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
    if on_progress:
        on_progress("verdict", result.verdict)

    # 5. Re-persist updated run record
    if result.run_dir:
        run_json_path = Path(result.run_dir) / "run.json"
        run_json_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")

    return result
