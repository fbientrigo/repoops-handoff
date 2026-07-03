import json
from pathlib import Path

from typer.testing import CliRunner

from repoops.cli import app

runner = CliRunner()


def _write_config(path: Path, *, repo_path: Path, report_dir: Path, snapshot_dir: Path) -> Path:
    path.write_text(
        f"""
        machine:
          name: nasapcdeb
        defaults:
          report_dir: {report_dir}
          snapshot_dir: {snapshot_dir}
          fetch: false
        repos:
          - name: repo
            path: {repo_path}
        """,
        encoding="utf-8",
    )
    return path


def test_run_command_fetch_flag_forces_fetch_even_if_config_false(
    tmp_path: Path, repo_with_upstream: Path
) -> None:
    report_dir = tmp_path / "reports"
    snapshot_dir = tmp_path / "snapshots"
    config_path = _write_config(
        tmp_path / "repos.yaml",
        repo_path=repo_with_upstream,
        report_dir=report_dir,
        snapshot_dir=snapshot_dir,
    )

    result = runner.invoke(app, ["run", "--config", str(config_path), "--fetch"])

    assert result.exit_code == 0, result.output
    snapshot_files = list(snapshot_dir.glob("*.json"))
    assert len(snapshot_files) == 1
    payload = json.loads(snapshot_files[0].read_text(encoding="utf-8"))
    assert payload["repos"][0]["remote"]["fetched"] is True


def test_scan_command_accepts_fetch_flag(tmp_path: Path, clean_git_repo: Path) -> None:
    config_path = tmp_path / "repos.yaml"
    config_path.write_text(
        f"""
        machine:
          name: nasapcdeb
        repos:
          - name: repo
            path: {clean_git_repo}
        """,
        encoding="utf-8",
    )

    result = runner.invoke(app, ["scan", "--config", str(config_path), "--fetch"])

    assert result.exit_code == 0, result.output
