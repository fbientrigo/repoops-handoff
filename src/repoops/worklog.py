"""Worklog evidence store — local, read-only, no exact hours, no final reports.

Persists scan snapshots (already-redacted metadata only, never file contents or
diffs) to SQLite and turns repeated activity into low-confidence candidate rows
for a human to review. `repoops` never decides worked hours; it only surfaces
evidence.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from repoops.config import RepoOpsConfig
from repoops.git_scan import Snapshot, redact_secret_like_path
from repoops.paths import ensure_dir

MAX_DAILY_HOURS = 4.0
STALE_STREAK_DAYS = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL,
    machine TEXT NOT NULL,
    project TEXT NOT NULL,
    repo TEXT NOT NULL,
    path TEXT NOT NULL,
    branch TEXT,
    head TEXT,
    dirty INTEGER NOT NULL,
    staged_count INTEGER NOT NULL,
    modified_count INTEGER NOT NULL,
    untracked_count INTEGER NOT NULL,
    deleted_count INTEGER NOT NULL,
    renamed_count INTEGER NOT NULL,
    conflicted_count INTEGER NOT NULL,
    ahead INTEGER,
    behind INTEGER,
    risk_flags TEXT NOT NULL,
    changed_paths_redacted TEXT NOT NULL,
    changed_paths_hash TEXT NOT NULL
);
"""


def open_store(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the worklog SQLite store."""
    path = Path(db_path)
    ensure_dir(path.parent)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def changed_paths_hash(redacted_paths: list[str]) -> str:
    """Deterministic hash of a redacted, sorted path list. Never hashes raw contents."""
    joined = "\n".join(sorted(redacted_paths))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _project_for_repo(config: RepoOpsConfig, repo_name: str) -> str:
    for repo in config.repos:
        if repo.name == repo_name:
            return repo.project or "unassigned"
    return "unassigned"


def record_snapshot(conn: sqlite3.Connection, config: RepoOpsConfig, snapshot: Snapshot) -> int:
    """Insert one worklog row per existing git repo in the snapshot. Returns rows inserted."""
    rows = 0
    for repo in snapshot.repos:
        if not repo.exists or not repo.is_git_repo:
            continue
        # Defense in depth: redact again here even though git_scan already redacts
        # notable_files, so this storage function is safe even if called directly.
        redacted = [redact_secret_like_path(p) for p in repo.notable_files]
        conn.execute(
            """INSERT INTO snapshots (
                observed_at, machine, project, repo, path, branch, head, dirty,
                staged_count, modified_count, untracked_count, deleted_count,
                renamed_count, conflicted_count, ahead, behind, risk_flags,
                changed_paths_redacted, changed_paths_hash
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snapshot.timestamp,
                snapshot.machine,
                _project_for_repo(config, repo.name),
                repo.name,
                repo.path,
                repo.branch,
                repo.head,
                int(repo.dirty),
                repo.counts.staged,
                repo.counts.modified,
                repo.counts.untracked,
                repo.counts.deleted,
                repo.counts.renamed,
                repo.counts.conflicted,
                repo.remote.ahead,
                repo.remote.behind,
                json.dumps(repo.risk_flags),
                json.dumps(redacted),
                changed_paths_hash(redacted),
            ),
        )
        rows += 1
    conn.commit()
    return rows


@dataclass
class WorklogCandidate:
    date: str
    project: str
    repos_touched: list[str]
    evidence_summary: str
    real_hours_estimate_range: str
    suggested_reportable_hours: float
    confidence: str
    needs_review: bool


def iso_week_range(week: str) -> tuple[date, date]:
    """Parse 'YYYY-Www' into its Monday..Sunday date range."""
    year_str, week_str = week.split("-W")
    year, wk = int(year_str), int(week_str)
    return date.fromisocalendar(year, wk, 1), date.fromisocalendar(year, wk, 7)


def month_range(month: str) -> tuple[date, date]:
    """Parse 'YYYY-MM' into its first..last date range."""
    year_str, month_str = month.split("-")
    year, mo = int(year_str), int(month_str)
    return date(year, mo, 1), date(year, mo, monthrange(year, mo)[1])


def _select_dirty(conn: sqlite3.Connection, start: date, end: date) -> list[sqlite3.Row]:
    # observed_at is a fixed-width ISO8601 string ("YYYY-MM-DDTHH:MM:SS±HH:MM"), so a
    # substring date-prefix comparison sorts/compares identically to a real date compare.
    cur = conn.execute(
        "SELECT * FROM snapshots WHERE dirty = 1 AND substr(observed_at, 1, 10) BETWEEN ? AND ? "
        "ORDER BY observed_at",
        (start.isoformat(), end.isoformat()),
    )
    return cur.fetchall()


def _confidence_for(snapshot_count: int) -> str:
    if snapshot_count <= 1:
        return "low"
    if snapshot_count <= 3:
        return "medium"
    return "high"


def compute_candidates(conn: sqlite3.Connection, start: date, end: date) -> list[WorklogCandidate]:
    """Group dirty snapshots by (day, project) into review candidates. Deterministic:
    same DB contents always produce the same ordered candidate list."""
    rows = _select_dirty(conn, start, end)

    groups: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    # (repo, changed_paths_hash) -> distinct days it showed up dirty in this window.
    diff_days: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        day = row["observed_at"][:10]
        groups[(day, row["project"])].append(row)
        diff_days[(row["repo"], row["changed_paths_hash"])].add(day)

    # A repo showing the *same* redacted diff, dirty, on 3+ distinct days in the queried
    # window looks as consistent with a stale uncommitted change as with real multi-day
    # work — flag every day of that streak for a human to judge, rather than guess.
    stale_diffs = {key for key, days in diff_days.items() if len(days) >= STALE_STREAK_DAYS}

    candidates: list[WorklogCandidate] = []
    for (day, project), day_rows in sorted(groups.items()):
        repos_touched = sorted({row["repo"] for row in day_rows})
        snapshot_count = len(day_rows)
        risk_flags = sorted({flag for row in day_rows for flag in json.loads(row["risk_flags"])})

        hours = min(MAX_DAILY_HOURS, float(snapshot_count))
        low = max(0.0, hours - 1)
        high = min(MAX_DAILY_HOURS, hours + 1)

        needs_review = any(
            (row["repo"], row["changed_paths_hash"]) in stale_diffs for row in day_rows
        )

        candidates.append(
            WorklogCandidate(
                date=day,
                project=project,
                repos_touched=repos_touched,
                evidence_summary=(
                    f"{snapshot_count} dirty snapshot(s) across {len(repos_touched)} repo(s) "
                    f"({', '.join(repos_touched)}); risk flags: {', '.join(risk_flags) or 'none'}"
                ),
                real_hours_estimate_range=f"{low:g}-{high:g}",
                suggested_reportable_hours=hours,
                confidence=_confidence_for(snapshot_count),
                needs_review=needs_review,
            )
        )
    return candidates


def write_candidates_csv(candidates: list[WorklogCandidate], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "date",
                "project",
                "repos_touched",
                "evidence_summary",
                "real_hours_estimate_range",
                "suggested_reportable_hours",
                "confidence",
                "needs_review",
            ]
        )
        for candidate in candidates:
            writer.writerow(
                [
                    candidate.date,
                    candidate.project,
                    "; ".join(candidate.repos_touched),
                    candidate.evidence_summary,
                    candidate.real_hours_estimate_range,
                    candidate.suggested_reportable_hours,
                    candidate.confidence,
                    candidate.needs_review,
                ]
            )
