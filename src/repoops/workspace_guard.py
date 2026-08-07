"""WorkspaceGuard: Enforces repository boundary invariants and path restrictions."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from repoops.agent_models import AgentRunResult, TaskContract, ToolStep

FILE_MUTATING_TOOLS = {
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "create_file",
    "edit_file",
    "append_file",
}

FILE_PARAM_KEYS = {
    "targetfile",
    "target_file",
    "filepath",
    "file_path",
    "path",
    "target",
}


def extract_tool_target_paths(step: ToolStep) -> list[str]:
    """Extract file path parameters from an observable tool step."""
    paths: list[str] = []
    if not isinstance(step.raw, dict):
        return paths

    # Check various nesting locations in NDJSON event structures
    candidates: list[dict] = []

    # Case 1: step_update -> tool_info -> parameters
    step_update = step.raw.get("step_update")
    if isinstance(step_update, dict):
        tool_info = step_update.get("tool_info")
        if isinstance(tool_info, dict):
            params = tool_info.get("parameters")
            if isinstance(params, dict):
                candidates.append(params)

    # Case 2: raw -> tool_info -> parameters
    tool_info = step.raw.get("tool_info")
    if isinstance(tool_info, dict):
        params = tool_info.get("parameters")
        if isinstance(params, dict):
            candidates.append(params)

    # Case 3: raw -> parameters / input / args
    for key in ("parameters", "input", "args", "arguments"):
        params = step.raw.get(key)
        if isinstance(params, dict):
            candidates.append(params)

    for params in candidates:
        for k, v in params.items():
            if isinstance(k, str) and k.lower() in FILE_PARAM_KEYS and isinstance(v, str):
                paths.append(v)

    return paths


def _is_path_inside_repo(target_path_str: str, repo_root: Path) -> bool:
    """Normalize Windows/POSIX path and check if it sits inside repo_root."""
    resolved_root = repo_root.resolve()
    path_obj = Path(target_path_str)
    if not path_obj.is_absolute():
        resolved_target = (resolved_root / path_obj).resolve()
    else:
        resolved_target = path_obj.resolve()

    try:
        resolved_target.relative_to(resolved_root)
        return True
    except ValueError:
        return False


def _is_path_allowed(rel_path_str: str, allowed_paths: list[str]) -> bool:
    """Check if a repository-relative path matches allowed_paths rules."""
    if not allowed_paths:
        return True

    posix_path = Path(rel_path_str).as_posix()
    for allowed in allowed_paths:
        posix_allowed = Path(allowed).as_posix()
        if posix_allowed.endswith("/"):
            prefix = posix_allowed
            dir_name = posix_allowed.rstrip("/")
            if posix_path.startswith(prefix) or posix_path == dir_name:
                return True
        else:
            if (
                posix_path == posix_allowed
                or posix_path.startswith(posix_allowed + "/")
                or fnmatch.fnmatch(posix_path, posix_allowed)
            ):
                return True
    return False


def inspect_workspace_policy(
    contract: TaskContract | None,
    result: AgentRunResult,
    repo_root: Path,
) -> tuple[str, list[str]]:
    """Evaluate workspace boundaries and path constraints on an execution result.

    Returns (workspace_policy_status, workspace_policy_violations).
    workspace_policy_status is "passed" or "violation".
    """
    resolved_root = repo_root.resolve()
    violations: list[str] = []

    # 1. Observable tool step file target validation
    for step in result.steps:
        target_paths = extract_tool_target_paths(step)
        for target_str in target_paths:
            if not _is_path_inside_repo(target_str, resolved_root):
                tool_name = step.tool or "file_tool"
                violations.append(
                    f"Observable tool step {step.index} ({tool_name}) targeted path "
                    f"outside repository boundary: '{target_str}'"
                )

    # 2. Git evidence boundary and allowed_paths validation
    git = result.git_evidence
    all_changed_paths = sorted(set(git.changed_files + git.added_files + git.deleted_files))

    if contract is not None and contract.allowed_paths:
        for p in all_changed_paths:
            if not _is_path_allowed(p, contract.allowed_paths):
                violations.append(
                    f"Git change in '{p}' is outside allowed_paths {contract.allowed_paths}"
                )

    status = "violation" if violations else "passed"
    return status, violations
