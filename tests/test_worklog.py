import json
from datetime import date
from pathlib import Path

from repoops.config import MachineConfig, RepoConfig, RepoOpsConfig
from repoops.git_scan import ChangeCounts, RepoSnapshot, Snapshot
from repoops.worklog import (
    compute_candidates,
    iso_week_range,
    month_range,
    open_store,
    record_snapshot,
    write_candidates_csv,
)


def _snapshot(timestamp: str, *, dirty: bool, notable_files: list[str] | None = None) -> Snapshot:
    repo = RepoSnapshot(
        name="repo",
        path="/tmp/repo",
        exists=True,
        is_git_repo=True,
        branch="main",
        head="abc123",
        dirty=dirty,
        counts=ChangeCounts(modified=1 if dirty else 0),
        notable_files=notable_files or [],
        risk_flags=["dirty"] if dirty else [],
    )
    return Snapshot(machine="test-machine", timestamp=timestamp, repos=[repo])


def _config(tmp_path: Path, *, project: str = "Apolo") -> RepoOpsConfig:
    return RepoOpsConfig(
        machine=MachineConfig(name="test-machine"),
        repos=[RepoConfig(name="repo", path=tmp_path, project=project)],
    )


def test_clean_repo_creates_no_candidate(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "worklog.db")
    record_snapshot(conn, _config(tmp_path), _snapshot("2026-07-06T09:00:00-04:00", dirty=False))

    candidates = compute_candidates(conn, date(2026, 7, 6), date(2026, 7, 6))

    assert candidates == []


def test_repeated_dirty_snapshots_create_one_candidate(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "worklog.db")
    cfg = _config(tmp_path)
    record_snapshot(conn, cfg, _snapshot("2026-07-06T09:00:00-04:00", dirty=True))
    record_snapshot(conn, cfg, _snapshot("2026-07-06T14:00:00-04:00", dirty=True))
    record_snapshot(conn, cfg, _snapshot("2026-07-06T18:00:00-04:00", dirty=True))

    candidates = compute_candidates(conn, date(2026, 7, 6), date(2026, 7, 6))

    assert len(candidates) == 1
    assert candidates[0].date == "2026-07-06"
    assert candidates[0].project == "Apolo"
    assert candidates[0].repos_touched == ["repo"]


def test_isolated_dirty_snapshot_is_low_confidence(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "worklog.db")
    record_snapshot(conn, _config(tmp_path), _snapshot("2026-07-06T09:00:00-04:00", dirty=True))

    candidates = compute_candidates(conn, date(2026, 7, 6), date(2026, 7, 6))

    assert len(candidates) == 1
    assert candidates[0].confidence == "low"


def test_secret_like_paths_are_redacted_before_storage(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "worklog.db")
    snapshot = _snapshot(
        "2026-07-06T09:00:00-04:00", dirty=True, notable_files=["secrets/api_token.txt"]
    )

    record_snapshot(conn, _config(tmp_path), snapshot)

    row = conn.execute("SELECT changed_paths_redacted FROM snapshots").fetchone()
    stored = json.loads(row["changed_paths_redacted"])
    assert "api_token" not in json.dumps(stored)
    assert "[REDACTED_SECRET_PATH]" in stored[0]


def test_suggested_hours_never_exceed_four_per_day(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "worklog.db")
    cfg = _config(tmp_path)
    for hour in range(10):
        record_snapshot(conn, cfg, _snapshot(f"2026-07-06T{hour:02d}:00:00-04:00", dirty=True))

    candidates = compute_candidates(conn, date(2026, 7, 6), date(2026, 7, 6))

    assert len(candidates) == 1
    assert candidates[0].suggested_reportable_hours == 4.0


def test_unchanged_diff_across_multiple_days_needs_review(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "worklog.db")
    cfg = _config(tmp_path)
    same_files = ["src/model.py"]
    for day in (6, 7, 8):
        record_snapshot(
            conn,
            cfg,
            _snapshot(f"2026-07-{day:02d}T09:00:00-04:00", dirty=True, notable_files=same_files),
        )

    candidates = compute_candidates(conn, date(2026, 7, 6), date(2026, 7, 8))

    assert all(c.needs_review for c in candidates)


def test_changing_diff_across_days_does_not_need_review(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "worklog.db")
    cfg = _config(tmp_path)
    for day in (6, 7, 8):
        record_snapshot(
            conn,
            cfg,
            _snapshot(
                f"2026-07-{day:02d}T09:00:00-04:00", dirty=True, notable_files=[f"day-{day}.py"]
            ),
        )

    candidates = compute_candidates(conn, date(2026, 7, 6), date(2026, 7, 8))

    assert all(not c.needs_review for c in candidates)


def test_weekly_export_is_deterministic(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "worklog.db")
    cfg = _config(tmp_path)
    record_snapshot(conn, cfg, _snapshot("2026-07-06T09:00:00-04:00", dirty=True))
    record_snapshot(conn, cfg, _snapshot("2026-07-07T09:00:00-04:00", dirty=True))

    first = compute_candidates(conn, date(2026, 7, 6), date(2026, 7, 12))
    second = compute_candidates(conn, date(2026, 7, 6), date(2026, 7, 12))

    path_a = tmp_path / "a.csv"
    path_b = tmp_path / "b.csv"
    write_candidates_csv(first, path_a)
    write_candidates_csv(second, path_b)

    assert path_a.read_bytes() == path_b.read_bytes()


def test_iso_week_and_month_range_parsing() -> None:
    start, end = iso_week_range("2026-W28")
    assert start.isoweekday() == 1
    assert end.isoweekday() == 7
    assert (end - start).days == 6

    start, end = month_range("2026-02")
    assert start == date(2026, 2, 1)
    assert end == date(2026, 2, 28)
