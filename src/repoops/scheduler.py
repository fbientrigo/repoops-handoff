"""Single-run scheduler primitive for RepoOps unattended execution."""

from __future__ import annotations

import uuid
from pathlib import Path

from pydantic import BaseModel

from repoops.agent_models import AgentRunConfig
from repoops.agent_runner import select_runner
from repoops.paths import ensure_dir
from repoops.task_backlog import (
    SchedulerLock,
    SchedulerLockedError,
    TaskBacklogError,
    current_iso_timestamp,
    get_integration_head_sha,
    load_backlog,
    run_next_task,
    select_next_task,
)

SCHEDULER_RUNS_DIRNAME = ".repoops/scheduler-runs"
SCHEDULER_RUN_SCHEMA_VERSION = "repoops.scheduler_run.v1"


class SchedulerRunResult(BaseModel):
    """Machine-readable persisted outcome of a single scheduler invocation."""

    schema_version: str = SCHEDULER_RUN_SCHEMA_VERSION
    scheduler_run_id: str
    timestamp: str
    selected_task_id: str | None = None
    agent_run_id: str | None = None
    task_verdict: str | None = None
    promoted_commit_sha: str | None = None
    integration_head_before: str | None = None
    integration_head_after: str | None = None
    outcome: str
    reason: str
    run_dir: str = ""


def persist_scheduler_run(repo_root: Path, result: SchedulerRunResult) -> Path:
    """Persist a SchedulerRunResult record to disk."""
    run_dir = ensure_dir(repo_root / SCHEDULER_RUNS_DIRNAME / result.scheduler_run_id)
    result.run_dir = str(run_dir)
    out_path = run_dir / "run.json"
    out_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return out_path


def run_scheduler_once(
    repo: Path,
    provider: str = "antigravity",
    model: str = "Gemini 3.5 Flash (Low)",
    config: AgentRunConfig | None = None,
    max_attempts: int = 1,
    tasks_dir: Path | None = None,
    worktrees_dir: Path | None = None,
    locks_dir: Path | None = None,
) -> SchedulerRunResult:
    """Execute at most ONE eligible task from the repository backlog under scheduler lock."""
    resolved_repo = Path(repo).expanduser().resolve()
    run_id = uuid.uuid4().hex
    timestamp = current_iso_timestamp()

    # 1. Acquire repository-level scheduler lock
    try:
        lock = SchedulerLock(resolved_repo, locks_dir=locks_dir)
        lock.acquire()
    except SchedulerLockedError as exc:
        result = SchedulerRunResult(
            scheduler_run_id=run_id,
            timestamp=timestamp,
            outcome="locked",
            reason=str(exc),
        )
        persist_scheduler_run(resolved_repo, result)
        return result

    try:
        integration_before = get_integration_head_sha(resolved_repo)
        run_cfg = config or AgentRunConfig(model=model)

        # 2. Inspect backlog and select task
        backlog = load_backlog(resolved_repo, tasks_dir=tasks_dir)
        selected_task = select_next_task(
            backlog, repo_root=resolved_repo, max_attempts=max_attempts
        )

        if selected_task is None:
            integration_after = get_integration_head_sha(resolved_repo) or integration_before
            result = SchedulerRunResult(
                scheduler_run_id=run_id,
                timestamp=timestamp,
                integration_head_before=integration_before,
                integration_head_after=integration_after,
                outcome="no_eligible_task",
                reason="No eligible tasks available in backlog",
            )
            persist_scheduler_run(resolved_repo, result)
            return result

        # 3. Execute task via existing task-run-next primitive
        runner = select_runner(provider)
        try:
            exec_outcome = run_next_task(
                resolved_repo,
                runner,
                config=run_cfg,
                tasks_dir=tasks_dir,
                worktrees_dir=worktrees_dir,
                max_attempts=max_attempts,
            )
        except TaskBacklogError as exc:
            integration_after = get_integration_head_sha(resolved_repo) or integration_before
            result = SchedulerRunResult(
                scheduler_run_id=run_id,
                timestamp=timestamp,
                selected_task_id=selected_task.id,
                integration_head_before=integration_before,
                integration_head_after=integration_after,
                outcome="error",
                reason=f"Task backlog error during execution: {exc}",
            )
            persist_scheduler_run(resolved_repo, result)
            return result
        except Exception as exc:
            integration_after = get_integration_head_sha(resolved_repo) or integration_before
            result = SchedulerRunResult(
                scheduler_run_id=run_id,
                timestamp=timestamp,
                selected_task_id=selected_task.id,
                integration_head_before=integration_before,
                integration_head_after=integration_after,
                outcome="error",
                reason=f"Unexpected execution error: {exc}",
            )
            persist_scheduler_run(resolved_repo, result)
            return result

        if exec_outcome is None:
            integration_after = get_integration_head_sha(resolved_repo) or integration_before
            result = SchedulerRunResult(
                scheduler_run_id=run_id,
                timestamp=timestamp,
                integration_head_before=integration_before,
                integration_head_after=integration_after,
                outcome="no_eligible_task",
                reason="No eligible task executed",
            )
            persist_scheduler_run(resolved_repo, result)
            return result

        task_item, agent_result, _ = exec_outcome
        integration_after = get_integration_head_sha(resolved_repo) or integration_before

        verdict = agent_result.verdict
        if verdict == "verified":
            outcome = "task_verified"
            reason = f"Task '{task_item.id}' verified and promoted successfully"
        elif verdict == "failed":
            outcome = "task_failed"
            reason = (
                task_item.last_failure_reason
                or f"Task '{task_item.id}' execution failed with verdict 'failed'"
            )
        elif verdict == "policy_violation":
            outcome = "task_policy_violation"
            reason = f"Task '{task_item.id}' caused a workspace policy violation"
        elif verdict == "unverified":
            outcome = "task_unverified"
            reason = f"Task '{task_item.id}' finished unverified"
        else:
            outcome = "error"
            reason = f"Task '{task_item.id}' finished with unknown verdict: {verdict}"

        result = SchedulerRunResult(
            scheduler_run_id=run_id,
            timestamp=timestamp,
            selected_task_id=task_item.id,
            agent_run_id=agent_result.run_id,
            task_verdict=verdict,
            promoted_commit_sha=task_item.promoted_commit_sha,
            integration_head_before=integration_before,
            integration_head_after=integration_after,
            outcome=outcome,
            reason=reason,
        )
        persist_scheduler_run(resolved_repo, result)
        return result

    finally:
        lock.release()
