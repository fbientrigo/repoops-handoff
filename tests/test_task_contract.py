"""Tests for TaskContract loading, validation, and prompt formatting."""

import json

import pytest

from repoops.agent_models import TaskContract
from repoops.task_contract import TaskContractError, build_task_prompt, load_task_contract


def test_valid_task_contract_yaml(tmp_path):
    contract_file = tmp_path / "task.yaml"
    contract_file.write_text(
        """
id: add-csv-validation
objective: Add input validation to the CSV importer.
expected_changes:
  required: true
allowed_paths:
  - src/
  - tests/
acceptance:
  - pytest -q tests/test_csv.py
""",
        encoding="utf-8",
    )
    contract = load_task_contract(contract_file)
    assert contract.id == "add-csv-validation"
    assert contract.objective == "Add input validation to the CSV importer."
    assert contract.expected_changes.required is True
    assert contract.allowed_paths == ["src/", "tests/"]
    assert contract.acceptance == ["pytest -q tests/test_csv.py"]


def test_valid_task_contract_json(tmp_path):
    contract_file = tmp_path / "task.json"
    data = {
        "id": "json-task",
        "objective": "Test json parsing",
        "expected_changes": {"required": False},
        "allowed_paths": ["app/"],
        "acceptance": ["echo ok"],
    }
    contract_file.write_text(json.dumps(data), encoding="utf-8")
    contract = load_task_contract(contract_file)
    assert contract.id == "json-task"
    assert contract.expected_changes.required is False


def test_invalid_task_contract_file_not_found(tmp_path):
    with pytest.raises(TaskContractError, match="TaskContract file not found"):
        load_task_contract(tmp_path / "nonexistent.yaml")


def test_invalid_task_contract_missing_required_fields(tmp_path):
    contract_file = tmp_path / "invalid.yaml"
    contract_file.write_text("objective: Missing ID field\n", encoding="utf-8")
    with pytest.raises(TaskContractError, match="Invalid TaskContract schema"):
        load_task_contract(contract_file)


def test_invalid_task_contract_bad_syntax(tmp_path):
    contract_file = tmp_path / "bad_syntax.yaml"
    contract_file.write_text("id: [unclosed list", encoding="utf-8")
    with pytest.raises(TaskContractError, match="Failed to parse TaskContract"):
        load_task_contract(contract_file)


def test_build_task_prompt(tmp_path):
    contract = TaskContract(
        id="test-prompt",
        objective="Fix memory leak",
        allowed_paths=["src/core/"],
        acceptance=["pytest tests/test_memory.py"],
    )
    prompt = build_task_prompt(contract, tmp_path)
    assert "Target Repository Root:" in prompt
    assert str(tmp_path.resolve().as_posix()) in prompt
    assert "Allowed Paths: src/core/" in prompt
    assert "Fix memory leak" in prompt
    assert "pytest tests/test_memory.py" in prompt
