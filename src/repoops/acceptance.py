"""Deterministic acceptance verification runner."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from repoops.agent_models import AcceptanceResult, TaskContract


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_acceptance_commands(
    contract: TaskContract | None,
    repo_root: Path,
    *,
    timeout_seconds: int = 300,
) -> tuple[str, list[AcceptanceResult]]:
    """Execute TaskContract acceptance commands independently in repo_root.

    Returns (acceptance_status, acceptance_results).
    acceptance_status is "passed", "failed", or "skipped".
    """
    if contract is None or not contract.acceptance:
        return "skipped", []

    resolved_root = repo_root.resolve()
    results: list[AcceptanceResult] = []

    for cmd in contract.acceptance:
        started_at = _now_iso()
        timed_out = False
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=resolved_root,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            ended_at = _now_iso()
            stdout_text = proc.stdout[:2000] if proc.stdout else ""
            stderr_text = proc.stderr[:2000] if proc.stderr else ""
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            ended_at = _now_iso()
            stdout_text = (exc.stdout or "")[:2000]
            msg = f"Command timed out after {timeout_seconds}s. "
            stderr_text = msg + (exc.stderr or "")[:2000]
            exit_code = -1
            timed_out = True

        passed = exit_code == 0 and not timed_out
        results.append(
            AcceptanceResult(
                command=cmd,
                started_at=started_at,
                ended_at=ended_at,
                exit_code=exit_code,
                stdout=stdout_text,
                stderr=stderr_text,
                passed=passed,
                timed_out=timed_out,
            )
        )

    all_passed = all(r.passed for r in results)
    acceptance_status = "passed" if all_passed else "failed"
    return acceptance_status, results
