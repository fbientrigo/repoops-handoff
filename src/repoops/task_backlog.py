"""Task backlog data model, eligibility checker, deterministic selector,
concurrency locking, Git worktree execution layer, and integration branch promotion.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from repoops.agent_models import AgentRunConfig, AgentRunResult, ExpectedChanges, TaskContract
from repoops.agent_runner import AgentRunner
from repoops.agent_verification import run_verified_task
from repoops.paths import atomic_write_text, ensure_dir
from repoops.progress import ProgressCallback
from repoops.workspace_guard import _is_path_allowed


class TaskBacklogError(Exception):
    """Base exception for task backlog operations."""


class TaskLockedError(TaskBacklogError):
    """Raised when attempting to launch a task that is currently locked."""


class SchedulerLockedError(TaskBacklogError):
    """Raised when attempting to run the scheduler when it is currently locked."""


class PromotionError(TaskBacklogError):
    """Raised when task code promotion fails."""


VALID_TASK_STATUSES = {"pending", "ready", "running", "verified", "failed", "blocked"}
VALID_PROMOTION_STATUSES = {"not_applicable", "pending", "promoted", "failed"}
INTEGRATION_BRANCH_NAME = "repoops/integration"


def current_iso_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class TaskItem(BaseModel):
    """Task backlog entry extending TaskContract with state and orchestration metadata."""

    id: str
    status: str = "ready"
    priority: int = 100
    depends_on: list[str] = Field(default_factory=list)
    objective: str
    expected_changes: ExpectedChanges = Field(default_factory=ExpectedChanges)
    allowed_paths: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)

    # Persistence & promotion metadata
    promotion_status: str = "not_applicable"
    baseline_ref: str | None = None
    baseline_sha: str | None = None
    promoted_commit_sha: str | None = None
    attempt_count: int = 0
    last_attempt_at: str | None = None
    last_failure_reason: str | None = None
    last_run_id: str | None = None
    last_verdict: str | None = None
    updated_at: str | None = None
    file_path: Path | None = Field(default=None, exclude=True)

    def to_task_contract(self) -> TaskContract:
        """Convert TaskItem to TaskContract for AgentRunner/run_verified_task."""
        return TaskContract(
            id=self.id,
            objective=self.objective,
            expected_changes=self.expected_changes,
            allowed_paths=self.allowed_paths,
            acceptance=self.acceptance,
        )


def load_task_item(path: Path) -> TaskItem:
    """Load and validate a TaskItem from a YAML or JSON file."""
    item_path = Path(path).expanduser().resolve()
    if not item_path.exists():
        raise TaskBacklogError(f"Task file not found: '{item_path}'")

    text = item_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except Exception:
        try:
            data = json.loads(text)
        except Exception as exc:
            raise TaskBacklogError(f"Failed to parse task file '{item_path}': {exc}") from exc

    if not isinstance(data, dict):
        raise TaskBacklogError(f"Task file '{item_path}' must contain a dictionary/object.")

    try:
        task = TaskItem.model_validate(data)
        task.file_path = item_path
        if task.status not in VALID_TASK_STATUSES:
            raise TaskBacklogError(
                f"Task '{task.id}' has invalid status '{task.status}'. "
                f"Valid statuses are: {sorted(VALID_TASK_STATUSES)}"
            )
        return task
    except ValidationError as exc:
        raise TaskBacklogError(f"Invalid task schema in '{item_path}': {exc}") from exc


def load_backlog(repo_root: Path, tasks_dir: Path | None = None) -> list[TaskItem]:
    """Scan and load all TaskItems from .repoops/tasks/ (or specified tasks_dir)."""
    target_dir = tasks_dir or (Path(repo_root).expanduser().resolve() / ".repoops" / "tasks")
    if not target_dir.exists() or not target_dir.is_dir():
        return []

    tasks: list[TaskItem] = []
    for entry in sorted(target_dir.iterdir(), key=lambda p: p.name.lower()):
        if (
            entry.is_file()
            and not entry.name.startswith(".")
            and entry.suffix.lower() in (".yaml", ".yml", ".json")
        ):
            tasks.append(load_task_item(entry))
    return tasks


def save_task(repo_root: Path, task: TaskItem, tasks_dir: Path | None = None) -> Path:
    """Save a TaskItem atomically to disk in YAML format."""
    target_dir = tasks_dir or (Path(repo_root).expanduser().resolve() / ".repoops" / "tasks")
    ensure_dir(target_dir)

    if task.file_path:
        out_path = task.file_path
    else:
        out_path = target_dir / f"{task.id}.yaml"
        task.file_path = out_path

    data = task.model_dump(mode="json", exclude_none=True, exclude={"file_path"})
    yaml_text = yaml.safe_dump(data, sort_keys=False)
    atomic_write_text(out_path, yaml_text)
    return out_path


def ensure_integration_branch(repo_root: Path) -> tuple[str, str, str]:
    """Ensure the local repoops/integration branch exists.

    Returns (branch_name, integration_head_sha, base_origin_sha).
    Never checks out or mutates the user's primary working branch.
    """
    resolved_repo = Path(repo_root).expanduser().resolve()

    # Get user's primary repo HEAD SHA
    proc_primary = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=resolved_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    primary_head_sha = proc_primary.stdout.strip()

    # Check if repoops/integration exists
    proc_check = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{INTEGRATION_BRANCH_NAME}"],
        cwd=resolved_repo,
        check=False,
        capture_output=True,
        text=True,
    )

    if proc_check.returncode == 0 and proc_check.stdout.strip():
        integration_sha = proc_check.stdout.strip()
        return INTEGRATION_BRANCH_NAME, integration_sha, primary_head_sha
    else:
        # Create repoops/integration at primary_head_sha
        subprocess.run(
            ["git", "branch", INTEGRATION_BRANCH_NAME, primary_head_sha],
            cwd=resolved_repo,
            check=True,
            capture_output=True,
        )
        return INTEGRATION_BRANCH_NAME, primary_head_sha, primary_head_sha


def get_integration_head_sha(repo_root: Path) -> str | None:
    """Get the current HEAD SHA of the repoops/integration branch if it exists."""
    resolved_repo = Path(repo_root).expanduser().resolve()
    proc_check = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{INTEGRATION_BRANCH_NAME}"],
        cwd=resolved_repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc_check.returncode == 0 and proc_check.stdout.strip():
        return proc_check.stdout.strip()
    return None


def is_ancestor_commit(repo_root: Path, ancestor_sha: str, descendant_sha: str) -> bool:
    """Check if ancestor_sha is a Git ancestor of descendant_sha."""
    resolved_repo = Path(repo_root).expanduser().resolve()
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
        cwd=resolved_repo,
        check=False,
        capture_output=True,
    )
    return proc.returncode == 0


def check_eligibility(
    task: TaskItem,
    backlog_map: dict[str, TaskItem],
    repo_root: Path | None = None,
    max_attempts: int | None = None,
) -> tuple[bool, str | None]:
    """Check if a task is eligible for execution.

    Requirements:
    1. attempt_count is less than max_attempts (if max_attempts is specified)
    2. status is 'ready'
    3. every task ID in depends_on exists in backlog
    4. every dependency task status is 'verified'
    5. every dependency task promotion_status is 'promoted'
    6. dependency promoted_commit_sha is an ancestor of current integration HEAD
    """
    if max_attempts is not None and task.attempt_count >= max_attempts:
        return False, f"max_attempts_reached ({task.attempt_count}/{max_attempts})"

    if task.status != "ready":
        return False, f"Task status is '{task.status}' (expected 'ready')"

    integration_sha = None
    if repo_root:
        _, integration_sha, _ = ensure_integration_branch(repo_root)

    for dep_id in task.depends_on:
        if dep_id not in backlog_map:
            return False, f"Dependency task '{dep_id}' does not exist in backlog"
        dep_task = backlog_map[dep_id]

        if dep_task.status != "verified":
            return (
                False,
                f"Dependency task '{dep_id}' status is '{dep_task.status}' (expected 'verified')",
            )

        if dep_task.promotion_status != "promoted" or not dep_task.promoted_commit_sha:
            return False, f"Dependency task '{dep_id}' is not promoted"

        if (
            repo_root
            and integration_sha
            and not is_ancestor_commit(repo_root, dep_task.promoted_commit_sha, integration_sha)
        ):
            return (
                False,
                f"Dependency '{dep_id}' commit {dep_task.promoted_commit_sha[:7]} "
                f"is not an ancestor of integration HEAD ({integration_sha[:7]})",
            )

    return True, None


def select_next_task(
    backlog: list[TaskItem],
    repo_root: Path | None = None,
    max_attempts: int | None = None,
) -> TaskItem | None:
    """Pure deterministic selector for the next eligible task."""
    backlog_map = {t.id: t for t in backlog}
    eligible: list[TaskItem] = []

    for task in backlog:
        is_eligible, _ = check_eligibility(
            task, backlog_map, repo_root=repo_root, max_attempts=max_attempts
        )
        if is_eligible:
            eligible.append(task)

    if not eligible:
        return None

    # Sort deterministically: (priority ascending, id ascending)
    eligible.sort(key=lambda t: (t.priority, t.id))
    return eligible[0]


def _is_pid_active(pid: int) -> bool:
    """Check if a process with given PID is alive locally."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            success = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            return bool(success and exit_code.value == 259)
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


class TaskLock:
    """Local file-based lock to prevent concurrent execution of the same task."""

    def __init__(self, repo_root: Path, task_id: str, locks_dir: Path | None = None):
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.task_id = task_id
        target_dir = locks_dir or (self.repo_root / ".repoops" / "locks")
        ensure_dir(target_dir)
        self.lock_path = target_dir / f"{task_id}.lock"
        self._fd: int | None = None

    def acquire(self) -> None:
        """Acquire the lock exclusively. Raises TaskLockedError if already locked."""
        if self.lock_path.exists():
            try:
                content = self.lock_path.read_text(encoding="utf-8").strip()
                lock_data = json.loads(content)
                pid = lock_data.get("pid")
                if pid and _is_pid_active(pid):
                    raise TaskLockedError(
                        f"Task '{self.task_id}' is locked by active process PID {pid}"
                    )
            except (json.JSONDecodeError, OSError):
                pass
            with contextlib.suppress(OSError):
                self.lock_path.unlink(missing_ok=True)

        try:
            fd = os.open(
                str(self.lock_path),
                os.O_CREAT | os.O_EXCL | os.O_RDWR,
            )
            self._fd = fd
            payload = json.dumps({"pid": os.getpid(), "acquired_at": current_iso_timestamp()})
            os.write(fd, payload.encode("utf-8"))
        except OSError as exc:
            raise TaskLockedError(
                f"Task '{self.task_id}' is locked by another process or concurrent run: {exc}"
            ) from exc

    def release(self) -> None:
        """Release lock and remove lockfile."""
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None

        with contextlib.suppress(OSError):
            self.lock_path.unlink(missing_ok=True)

    def __enter__(self) -> TaskLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


class SchedulerLock:
    """Repository-level local file-based lock to prevent concurrent scheduler runs."""

    def __init__(self, repo_root: Path, locks_dir: Path | None = None):
        self.repo_root = Path(repo_root).expanduser().resolve()
        target_dir = locks_dir or (self.repo_root / ".repoops" / "locks")
        ensure_dir(target_dir)
        self.lock_path = target_dir / "scheduler.lock"
        self._fd: int | None = None

    def acquire(self) -> None:
        """Acquire the scheduler lock exclusively. Raises SchedulerLockedError if locked."""
        if self.lock_path.exists():
            try:
                content = self.lock_path.read_text(encoding="utf-8").strip()
                lock_data = json.loads(content)
                pid = lock_data.get("pid")
                if pid and _is_pid_active(pid):
                    raise SchedulerLockedError(f"Scheduler is locked by active process PID {pid}")
            except (json.JSONDecodeError, OSError):
                pass
            with contextlib.suppress(OSError):
                self.lock_path.unlink(missing_ok=True)

        try:
            fd = os.open(
                str(self.lock_path),
                os.O_CREAT | os.O_EXCL | os.O_RDWR,
            )
            self._fd = fd
            payload = json.dumps({"pid": os.getpid(), "acquired_at": current_iso_timestamp()})
            os.write(fd, payload.encode("utf-8"))
        except OSError as exc:
            raise SchedulerLockedError(
                f"Scheduler is locked by another process or concurrent run: {exc}"
            ) from exc

    def release(self) -> None:
        """Release lock and remove lockfile."""
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None

        with contextlib.suppress(OSError):
            self.lock_path.unlink(missing_ok=True)

    def __enter__(self) -> SchedulerLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


def create_task_worktree(
    repo_root: Path, task_id: str, worktrees_dir: Path | None = None
) -> tuple[Path, str]:
    """Create an isolated Git worktree under .repoops/worktrees/<task_id>/
    from repoops/integration HEAD.

    Returns (worktree_path, baseline_sha).
    """
    resolved_repo = Path(repo_root).expanduser().resolve()
    _, baseline_sha, _ = ensure_integration_branch(resolved_repo)

    target_dir = worktrees_dir or (resolved_repo / ".repoops" / "worktrees")
    ensure_dir(target_dir)
    wt_path = target_dir / task_id

    if wt_path.exists():
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_path)],
            cwd=resolved_repo,
            check=False,
            capture_output=True,
        )

    subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt_path), baseline_sha],
        cwd=resolved_repo,
        check=True,
        capture_output=True,
        text=True,
    )

    return wt_path, baseline_sha


def promote_task(
    repo_root: Path,
    task: TaskItem,
    result: AgentRunResult,
    wt_path: Path,
) -> tuple[str, str | None, str | None]:
    """Promote verified task changes to the repoops/integration branch.

    Returns (promotion_status, promoted_commit_sha, promotion_error).
    `promotion_status` is "promoted" or "failed".
    """
    resolved_repo = Path(repo_root).expanduser().resolve()
    resolved_wt = Path(wt_path).resolve()

    # 1. Pre-promotion verification assertions
    if result.verdict != "verified":
        return "failed", None, f"Cannot promote task with verdict '{result.verdict}'"
    if result.workspace_policy_status != "passed":
        return "failed", None, "Cannot promote task with workspace_policy_status violation"
    if result.acceptance_status != "passed":
        msg = f"Cannot promote task with acceptance_status '{result.acceptance_status}'"
        return "failed", None, msg

    git_ev = result.git_evidence
    all_changed_paths = sorted(
        set(git_ev.changed_files + git_ev.added_files + git_ev.deleted_files)
    )
    if task.expected_changes.required and len(all_changed_paths) == 0:
        msg = "Cannot promote task: expected_changes required but 0 Git changes present"
        return "failed", None, msg

    # 2. Strict allowed_path & .repoops/ boundary checking
    for rel_path in all_changed_paths:
        posix_rel = Path(rel_path).as_posix()
        if posix_rel.startswith(".repoops/") or posix_rel == ".repoops":
            return (
                "failed",
                None,
                f"Promotion rejected: file '{rel_path}' is under .repoops/ directory",
            )
        if task.allowed_paths and not _is_path_allowed(rel_path, task.allowed_paths):
            msg = (
                f"Promotion rejected: file '{rel_path}' is outside "
                f"allowed_paths {task.allowed_paths}"
            )
            return ("failed", None, msg)

    # 3. Stage permitted changes in worktree
    # Stage deleted files
    for deleted in git_ev.deleted_files:
        subprocess.run(
            ["git", "rm", "--ignore-unmatch", deleted],
            cwd=resolved_wt,
            check=False,
            capture_output=True,
        )

    # Stage added/changed files
    to_stage = git_ev.added_files + git_ev.changed_files
    if to_stage:
        proc_add = subprocess.run(
            ["git", "add", *to_stage],
            cwd=resolved_wt,
            check=False,
            capture_output=True,
            text=True,
        )
        if proc_add.returncode != 0:
            return "failed", None, f"Failed to stage files for promotion: {proc_add.stderr}"

    # 4. Create deterministic commit inside worktree
    commit_msg = (
        f"repoops({task.id}): verified implementation\n\n"
        f"Run-ID: {result.run_id}\n"
        f"Verdict: {result.verdict}\n"
    )
    proc_commit = subprocess.run(
        ["git", "commit", "-m", commit_msg],
        cwd=resolved_wt,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc_commit.returncode != 0:
        return "failed", None, f"Git commit failed during promotion: {proc_commit.stderr}"

    # Get new commit SHA
    proc_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=resolved_wt,
        check=True,
        capture_output=True,
        text=True,
    )
    promoted_sha = proc_sha.stdout.strip()

    # 5. Advance repoops/integration branch in primary repo
    proc_ref = subprocess.run(
        ["git", "update-ref", f"refs/heads/{INTEGRATION_BRANCH_NAME}", promoted_sha],
        cwd=resolved_repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc_ref.returncode != 0:
        return (
            "failed",
            None,
            f"Failed to advance {INTEGRATION_BRANCH_NAME} to {promoted_sha}: {proc_ref.stderr}",
        )

    return "promoted", promoted_sha, None


def run_next_task(
    repo_root: Path,
    runner: AgentRunner,
    config: AgentRunConfig,
    tasks_dir: Path | None = None,
    worktrees_dir: Path | None = None,
    max_attempts: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[TaskItem, AgentRunResult, Path] | None:
    """Execute at most ONE eligible task from the backlog in an isolated Git worktree.

    Returns (task, result, worktree_path) or None if no task was eligible.
    """
    resolved_repo = Path(repo_root).expanduser().resolve()
    backlog = load_backlog(resolved_repo, tasks_dir=tasks_dir)
    selected_task = select_next_task(backlog, repo_root=resolved_repo, max_attempts=max_attempts)

    if selected_task is None:
        return None

    with TaskLock(resolved_repo, selected_task.id):
        # Record attempt metadata
        selected_task.attempt_count += 1
        selected_task.last_attempt_at = current_iso_timestamp()
        selected_task.status = "running"
        save_task(resolved_repo, selected_task, tasks_dir=tasks_dir)

        # Create isolated worktree starting from repoops/integration HEAD
        wt_path, baseline_sha = create_task_worktree(
            resolved_repo, selected_task.id, worktrees_dir=worktrees_dir
        )
        selected_task.baseline_ref = INTEGRATION_BRANCH_NAME
        selected_task.baseline_sha = baseline_sha
        save_task(resolved_repo, selected_task, tasks_dir=tasks_dir)
        if on_progress:
            on_progress("git", "worktree ready")

        try:
            contract = selected_task.to_task_contract()
            result = run_verified_task(
                runner, contract, wt_path, config=config, on_progress=on_progress
            )

            selected_task.last_run_id = result.run_id
            selected_task.last_verdict = result.verdict
            selected_task.updated_at = current_iso_timestamp()

            if result.verdict == "verified":
                prom_status, prom_sha, prom_err = promote_task(
                    resolved_repo, selected_task, result, wt_path
                )
                if prom_status == "promoted":
                    selected_task.status = "verified"
                    selected_task.promotion_status = "promoted"
                    selected_task.promoted_commit_sha = prom_sha
                    selected_task.last_failure_reason = None
                    save_task(resolved_repo, selected_task, tasks_dir=tasks_dir)

                    if on_progress and prom_sha:
                        on_progress("promote", f"{INTEGRATION_BRANCH_NAME} -> {prom_sha[:7]}")

                    # Remove worktree cleanly after successful promotion
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(wt_path)],
                        cwd=resolved_repo,
                        check=False,
                        capture_output=True,
                    )
                else:
                    selected_task.status = "failed"
                    selected_task.promotion_status = "failed"
                    selected_task.last_failure_reason = prom_err
                    save_task(resolved_repo, selected_task, tasks_dir=tasks_dir)
                    if on_progress:
                        on_progress("promote", f"failed: {prom_err}")
            else:
                selected_task.status = "failed"
                selected_task.promotion_status = "not_applicable"
                reason = (
                    result.verification_notes[0]
                    if result.verification_notes
                    else f"Verdict: {result.verdict}"
                )
                selected_task.last_failure_reason = reason
                save_task(resolved_repo, selected_task, tasks_dir=tasks_dir)

            return selected_task, result, wt_path

        except BaseException as exc:
            selected_task.status = "failed"
            selected_task.promotion_status = "failed"
            selected_task.last_failure_reason = str(exc)
            selected_task.updated_at = current_iso_timestamp()
            save_task(resolved_repo, selected_task, tasks_dir=tasks_dir)
            raise
