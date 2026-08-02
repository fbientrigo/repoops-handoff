import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
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


def test_cli_version_output() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == "repoops 0.1.0"


def test_cli_missing_config_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Ensure default path points to a non-existent file
    fake_default = tmp_path / "non_existent_repos.yaml"
    monkeypatch.setattr("repoops.config.DEFAULT_CONFIG_PATH", fake_default)
    monkeypatch.delenv("REPOOPS_CONFIG", raising=False)

    result = runner.invoke(app, ["scan"])
    assert result.exit_code != 0
    assert "Config file not found" in result.output
    assert "--config" in result.output
    assert "REPOOPS_CONFIG" in result.output


def test_cli_filtering_and_excluded_repos_not_scanned(tmp_path: Path, clean_git_repo: Path) -> None:
    non_existent_repo = tmp_path / "does_not_exist_repo"
    snapshot_dir = tmp_path / "snapshots"
    report_dir = tmp_path / "reports"
    config_path = tmp_path / "repos.yaml"
    config_path.write_text(
        f"""
        machine:
          name: test-machine
        defaults:
          snapshot_dir: {snapshot_dir}
          report_dir: {report_dir}
        repos:
          - name: valid-repo
            path: {clean_git_repo}
            project: thesis
            tags: [thesis, ship]
          - name: bad-repo
            path: {non_existent_repo}
            project: broken
            tags: [broken]
        """,
        encoding="utf-8",
    )

    # Filter for valid-repo -> bad-repo is excluded and never scanned
    res_proj = runner.invoke(app, ["run", "--config", str(config_path), "--project", "thesis"])
    assert res_proj.exit_code == 0, res_proj.output
    snapshots = list(snapshot_dir.glob("*.json"))
    assert len(snapshots) == 1
    payload = json.loads(snapshots[0].read_text(encoding="utf-8"))
    scanned_names = [r["name"] for r in payload["repos"]]
    assert scanned_names == ["valid-repo"]

    # Filter with repeatable --tag
    snapshots[0].unlink()
    res_tags = runner.invoke(
        app, ["run", "--config", str(config_path), "--tag", "thesis", "--tag", "ship"]
    )
    assert res_tags.exit_code == 0, res_tags.output
    snapshots = list(snapshot_dir.glob("*.json"))
    payload = json.loads(snapshots[0].read_text(encoding="utf-8"))
    assert [r["name"] for r in payload["repos"]] == ["valid-repo"]

    # Filter with no match exits non-zero and lists known projects/tags
    res_nomatch = runner.invoke(
        app, ["scan", "--config", str(config_path), "--project", "nonexistent"]
    )
    assert res_nomatch.exit_code != 0
    assert "No repositories matched requested filters" in res_nomatch.output
    assert "Known projects: broken, thesis" in res_nomatch.output
    assert "Known tags: broken, ship, thesis" in res_nomatch.output
