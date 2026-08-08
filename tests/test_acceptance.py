"""Tests for deterministic post-run acceptance command execution."""

import sys

from repoops.acceptance import run_acceptance_commands
from repoops.agent_models import TaskContract


def test_acceptance_success(tmp_path):
    contract = TaskContract(
        id="acc1",
        objective="Run passing command",
        acceptance=[f'{sys.executable} -c "print(\\"hello world\\")"'],
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


def test_acceptance_progress_callback_multi_commands(tmp_path):
    contract = TaskContract(
        id="acc_multi",
        objective="Multiple acceptance commands",
        acceptance=[
            f'{sys.executable} -c "print(\\"step1\\")"',
            f'{sys.executable} -c "import sys; sys.exit(7)"',
        ],
    )
    logged: list[tuple[str, str]] = []
    status, results = run_acceptance_commands(
        contract, tmp_path, on_progress=lambda s, m: logged.append((s, m))
    )
    assert status == "failed"
    assert len(results) == 2
    assert results[0].passed is True
    assert results[1].passed is False

    assert logged == [
        ("verify", f"acceptance 1/2 started: {contract.acceptance[0]}"),
        ("verify", "acceptance 1/2 PASS"),
        ("verify", f"acceptance 2/2 started: {contract.acceptance[1]}"),
        ("verify", "acceptance 2/2 FAIL exit=7"),
    ]


def test_acceptance_progress_callback_timeout(tmp_path):
    contract = TaskContract(
        id="acc_timeout",
        objective="Timed out acceptance command",
        acceptance=[f'{sys.executable} -c "import time; time.sleep(10)"'],
    )
    logged: list[tuple[str, str]] = []
    status, results = run_acceptance_commands(
        contract, tmp_path, timeout_seconds=1, on_progress=lambda s, m: logged.append((s, m))
    )
    assert status == "failed"
    assert len(results) == 1
    assert results[0].timed_out is True
    assert results[0].passed is False

    assert logged == [
        ("verify", f"acceptance 1/1 started: {contract.acceptance[0]}"),
        ("verify", "acceptance 1/1 FAIL (timed out after 1s)"),
    ]
