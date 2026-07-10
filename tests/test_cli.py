import json
import sqlite3
from datetime import datetime
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


def test_worklog_scan_records_a_row_and_export_writes_csv(
    tmp_path: Path, clean_git_repo: Path
) -> None:
    worklog_db = tmp_path / "worklog.db"
    report_dir = tmp_path / "reports"
    config_path = tmp_path / "repos.yaml"
    config_path.write_text(
        f"""
        machine:
          name: nasapcdeb
        defaults:
          worklog_db: {worklog_db}
          report_dir: {report_dir}
          remote_check: false
        repos:
          - name: repo
            path: {clean_git_repo}
            project: Apolo
        """,
        encoding="utf-8",
    )

    scan_result = runner.invoke(app, ["worklog-scan", "--config", str(config_path)])
    assert scan_result.exit_code == 0, scan_result.output
    assert worklog_db.exists()

    conn = sqlite3.connect(worklog_db)
    row_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    conn.close()
    assert row_count == 1

    month = datetime.now().strftime("%Y-%m")
    export_result = runner.invoke(
        app, ["worklog-export", "--config", str(config_path), "--month", month]
    )
    assert export_result.exit_code == 0, export_result.output

    csv_path = report_dir / f"repoops-worklog-{month}.csv"
    assert csv_path.exists()
    assert csv_path.read_text(encoding="utf-8").startswith("date,project,repos_touched")
