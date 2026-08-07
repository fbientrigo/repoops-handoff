"""TaskContract loader and execution prompt builder."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from repoops.agent_models import TaskContract


class TaskContractError(Exception):
    """Raised when a task contract file cannot be found or parsed."""


def load_task_contract(path: Path) -> TaskContract:
    """Load and validate a TaskContract from a YAML or JSON file."""
    contract_path = Path(path).expanduser().resolve()
    if not contract_path.exists():
        raise TaskContractError(f"TaskContract file not found: '{contract_path}'")

    text = contract_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except Exception as exc:
        try:
            data = json.loads(text)
        except Exception:
            raise TaskContractError(f"Failed to parse TaskContract as YAML or JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise TaskContractError("TaskContract content must be a YAML or JSON object/dictionary.")

    try:
        return TaskContract.model_validate(data)
    except ValidationError as exc:
        raise TaskContractError(f"Invalid TaskContract schema: {exc}") from exc


def build_task_prompt(contract: TaskContract, repo_root: Path) -> str:
    """Build the defense-in-depth execution prompt passed to the agent runner."""
    allowed_str = (
        ", ".join(contract.allowed_paths)
        if contract.allowed_paths
        else "Any path inside repository"
    )
    acceptance_str = (
        "\n".join(f"- {cmd}" for cmd in contract.acceptance)
        if contract.acceptance
        else "None specified"
    )

    repo_posix = repo_root.resolve().as_posix()
    return f"""Target Repository Root: {repo_posix}
Allowed Paths: {allowed_str}
Required Changes: {contract.expected_changes.required}

Task ID: {contract.id}

Objective:
{contract.objective.strip()}

Acceptance Criteria / Commands:
{acceptance_str}

CRITICAL RULES FOR AGENT EXECUTION:
1. All file modifications MUST occur strictly inside the target repository root: {repo_posix}.
2. Do NOT write or create files outside target repository boundaries or in temporary directories.
3. Keep changes strictly within allowed paths: {allowed_str}.
"""
