"""Tests for WorkspaceGuard boundary checks and path normalization."""

from repoops.agent_models import AgentRunResult, GitEvidence, TaskContract, ToolStep
from repoops.workspace_guard import _is_path_inside_repo, inspect_workspace_policy


def test_tool_step_targeting_outside_repo(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    outside_file = tmp_path / "outside.txt"

    step = ToolStep(
        index=1,
        type="step_update",
        tool="write_to_file",
        raw={
            "step_update": {
                "tool_info": {
                    "name": "write_to_file",
                    "parameters": {"TargetFile": str(outside_file)},
                }
            }
        },
    )

    result = AgentRunResult(
        run_id="run1",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        steps=[step],
    )

    contract = TaskContract(
        id="t1",
        objective="Test outside write",
        allowed_paths=["src/"],
    )

    status, violations = inspect_workspace_policy(contract, result, repo_root)
    assert status == "violation"
    assert any("outside repository boundary" in v for v in violations)


def test_git_change_outside_allowed_paths(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    result = AgentRunResult(
        run_id="run2",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        git_evidence=GitEvidence(changed_files=["src/ok.py", "unallowed/bad.py"]),
    )

    contract = TaskContract(
        id="t2",
        objective="Test allowed paths",
        allowed_paths=["src/"],
    )

    status, violations = inspect_workspace_policy(contract, result, repo_root)
    assert status == "violation"
    assert any("unallowed/bad.py" in v for v in violations)


def test_required_change_with_zero_git_changes(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    result = AgentRunResult(
        run_id="run3",
        provider="antigravity",
        requested_model="model",
        repository=str(repo_root),
        started_at="2026-08-07T00:00:00Z",
        ended_at="2026-08-07T00:00:01Z",
        exit_code=0,
        process_status="completed",
        process_exit_status="success",
        git_evidence=GitEvidence(changed_files=[]),
    )

    contract = TaskContract(
        id="t3",
        objective="Test required changes",
        allowed_paths=["src/"],
    )

    status, violations = inspect_workspace_policy(contract, result, repo_root)
    assert status == "passed"
    assert len(violations) == 0


def test_windows_path_normalization(tmp_path):
    repo_root = tmp_path / "my_repo"
    repo_root.mkdir()

    inside_rel = "src/nested/file.txt"
    inside_win_rel = "src\\nested\\file.txt"
    outside_abs = str((tmp_path / "outside.txt").resolve())

    assert _is_path_inside_repo(inside_rel, repo_root) is True
    assert _is_path_inside_repo(inside_win_rel, repo_root) is True
    assert _is_path_inside_repo(outside_abs, repo_root) is False
