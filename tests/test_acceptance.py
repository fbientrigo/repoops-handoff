"""Tests for deterministic post-run acceptance command execution."""

import sys

from repoops.acceptance import run_acceptance_commands
from repoops.agent_models import TaskContract


def test_acceptance_success(tmp_path):
    contract = TaskContract(
        id="acc1",
        objective="Run passing command",
        acceptance=[f'{sys.executable} -c "print(\\\"hello world\\\")"'],
    )
    status, results = run_acceptance_commands(contract, tmp_path)
    assert status == "passed"
    assert len(results) == 1
    assert results[0].passed is True
    assert "hello world" in results[0].stdout
    assert results[0].exit_code == 0


def test_acceptance_failure(tmp_path):
    contract = TaskContract(
        id="acc2",
        objective="Run failing command",
        acceptance=[f'{sys.executable} -c "import sys; sys.exit(42)"'],
    )
    status, results = run_acceptance_commands(contract, tmp_path)
    assert status == "failed"
    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].exit_code == 42


def test_acceptance_skipped_when_empty(tmp_path):
    contract = TaskContract(
        id="acc3",
        objective="No acceptance commands",
        acceptance=[],
    )
    status, results = run_acceptance_commands(contract, tmp_path)
    assert status == "skipped"
    assert results == []
