"""Deterministic checkpoint/resume handoff generation (`repoops checkpoint` / `repoops resume`).

Read-only with respect to the target repository except for writing exactly two
files: `.repoops/handoff.json` and `.repoops/HANDOFF.md`. Never runs `git pull`,
`git push`, `git reset`, `git clean`, `git fetch`, or any other mutating or
network-touching Git command. Never reads file contents or full diffs — only
Git metadata (branch, HEAD, porcelain status, `diff --stat` summaries, and a
fixed-size recent commit log), reusing the same whitelisted `_run_git` and
path-redaction machinery as `repoops.git_scan`.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from repoops.git_scan import (
    ChangeCounts,
    _notable_files,
    _remote_sync_status,
    _run_git,
    parse_porcelain_status,
    redact_secret_like_path,
)
from repoops.handoff_models import (
    HANDOFF_SCHEMA_VERSION,
    ChangesInfo,
    DriftItem,
    Handoff,
    NextAction,
    RecentCommit,
    RepositoryInfo,
    ResumeReport,
    SemanticSection,
    Severity,
)
from repoops.handoff_render import render_handoff_markdown
from repoops.paths import atomic_write_text, ensure_dir

HANDOFF_DIRNAME = ".repoops"
HANDOFF_JSON_NAME = "handoff.json"
HANDOFF_MD_NAME = "HANDOFF.md"

MAX_NOTABLE_PATHS = 30
_LOG_FIELD_SEP = "\x1f"

_SHOW_TOPLEVEL_ARGS: tuple[str, ...] = ("rev-parse", "--show-toplevel")
_HEAD_FULL_ARGS: tuple[str, ...] = ("rev-parse", "HEAD")
_DIFF_STAT_ARGS: tuple[str, ...] = ("diff", "--stat")
_CACHED_DIFF_STAT_ARGS: tuple[str, ...] = ("diff", "--cached", "--stat")
_RECENT_LOG_ARGS: tuple[str, ...] = (
    "log",
    "-5",
    f"--pretty=format:%h{_LOG_FIELD_SEP}%ad{_LOG_FIELD_SEP}%s",
    "--date=iso-strict",
)


class HandoffError(RuntimeError):
    """Raised when a checkpoint/resume operation cannot proceed (e.g. not a Git repo)."""


def discover_repo_root(path: str | Path) -> Path:
    """Resolve the Git repository root containing `path`. Read-only; never mutates."""
    target = Path(path).expanduser().resolve(strict=False)
    if not target.exists():
        raise HandoffError(f"Path does not exist: {target}")
    if not target.is_dir():
        target = target.parent

    result = _run_git(target, _SHOW_TOPLEVEL_ARGS)
    if result.returncode != 0 or not result.stdout.strip():
        raise HandoffError(f"Not a Git repository (or any parent up to the mount point): {target}")
    return Path(result.stdout.strip()).resolve()


def handoff_paths(root: Path) -> tuple[Path, Path]:
    """Return (handoff.json path, HANDOFF.md path) for a repository root."""
    handoff_dir = root / HANDOFF_DIRNAME
    return handoff_dir / HANDOFF_JSON_NAME, handoff_dir / HANDOFF_MD_NAME


def _redact_diff_stat_path(raw_path: str) -> str:
    raw_path = raw_path.strip()
    if " => " in raw_path:
        left, right = raw_path.split(" => ", 1)
        return f"{redact_secret_like_path(left)} => {redact_secret_like_path(right)}"
    return redact_secret_like_path(raw_path)


def _is_handoff_dir_path(path: str) -> bool:
    """Whether a repo-relative path is inside `.repoops/` — the checkpoint's own output."""
    normalized = path.strip().strip('"').rstrip("/")
    return normalized == HANDOFF_DIRNAME or normalized.startswith(f"{HANDOFF_DIRNAME}/")


def _filter_handoff_dir_from_status(porcelain_text: str) -> str:
    """Drop `.repoops/` entries from `git status --porcelain=v1` output.

    Writing a checkpoint creates `.repoops/handoff.json` and `.repoops/HANDOFF.md`,
    which would otherwise show up as a new untracked entry on the very next scan —
    a self-inflicted drift signal with no bearing on the tracked work. Excluding the
    tool's own output directory keeps counts/dirty/notable_paths/diff stats
    describing only the repository's actual work.
    """
    kept: list[str] = []
    for line in porcelain_text.splitlines():
        if not line:
            continue
        raw_path = line[3:] if len(line) > 3 else ""
        path = raw_path.split(" -> ", 1)[1] if " -> " in raw_path else raw_path
        if _is_handoff_dir_path(path):
            continue
        kept.append(line)
    return "\n".join(kept)


def redact_diff_stat(text: str) -> str:
    """Redact secret-like filenames from `git diff --stat` output, dropping `.repoops/` lines.

    `diff --stat` output is filenames plus insertion/deletion counts, never file
    contents — but a secret-like filename (e.g. `.env`) must still be redacted
    the same way it is in porcelain status and notable-file lists.
    """
    lines: list[str] = []
    for line in text.splitlines():
        if "|" not in line:
            lines.append(line)
            continue
        path_part, _, rest = line.partition("|")
        candidate = path_part.strip()
        check_path = candidate.split(" => ", 1)[0] if " => " in candidate else candidate
        if _is_handoff_dir_path(check_path):
            continue
        leading_ws = path_part[: len(path_part) - len(path_part.lstrip())]
        redacted_path = _redact_diff_stat_path(path_part)
        lines.append(f"{leading_ws}{redacted_path} |{rest}")
    return "\n".join(lines)


def _parse_recent_commits(raw: str) -> list[RecentCommit]:
    commits: list[RecentCommit] = []
    for line in raw.splitlines():
        if not line:
            continue
        parts = line.split(_LOG_FIELD_SEP)
        if len(parts) != 3:
            continue
        short_hash, commit_date, subject = parts
        commits.append(RecentCommit(short_hash=short_hash, date=commit_date, subject=subject))
    return commits


def collect_repository_facts(root: Path) -> tuple[RepositoryInfo, ChangesInfo, list[RecentCommit]]:
    """Collect deterministic, read-only Git facts for `root`.

    Never fetches (upstream ahead/behind are computed from local refs only) and
    never reads file contents.
    """
    branch_raw = _run_git(root, ("rev-parse", "--abbrev-ref", "HEAD")).stdout.strip()
    detached = branch_raw in ("HEAD", "")
    branch = None if detached else branch_raw

    head_short = _run_git(root, ("rev-parse", "--short", "HEAD")).stdout.strip()
    head_full = _run_git(root, _HEAD_FULL_ARGS).stdout.strip()

    remote = _remote_sync_status(root, remote_check=True, fetch=False, fetch_timeout_seconds=1)

    status_result = _run_git(root, ("status", "--porcelain=v1"))
    filtered_status = _filter_handoff_dir_from_status(status_result.stdout)
    summary = parse_porcelain_status(filtered_status)

    notable_paths = _notable_files(summary, max_files=MAX_NOTABLE_PATHS, include_untracked=True)

    diff_stat = redact_diff_stat(_run_git(root, _DIFF_STAT_ARGS).stdout)
    cached_diff_stat = redact_diff_stat(_run_git(root, _CACHED_DIFF_STAT_ARGS).stdout)

    recent_commits = _parse_recent_commits(_run_git(root, _RECENT_LOG_ARGS).stdout)

    repository = RepositoryInfo(
        name=root.name,
        root=str(root),
        branch=branch,
        detached_head=detached,
        head_short=head_short,
        head_full=head_full,
        upstream=remote.upstream,
        ahead=remote.ahead,
        behind=remote.behind,
        dirty=summary.dirty,
    )
    changes = ChangesInfo(
        counts=summary.counts,
        notable_paths=notable_paths,
        diff_stat=diff_stat,
        cached_diff_stat=cached_diff_stat,
    )
    return repository, changes, recent_commits


def create_checkpoint(path: str | Path) -> Handoff:
    """Collect current repo state and write `.repoops/handoff.json` + `HANDOFF.md`.

    The semantic section (goal, scope, decisions, ...) is never inferred — every
    checkpoint starts with explicit `TODO:` placeholders for a human or agent to
    fill in. This is the only function in `repoops.handoff` that writes files, and
    it writes exactly these two, atomically.
    """
    root = discover_repo_root(path)
    repository, changes, recent_commits = collect_repository_facts(root)

    handoff = Handoff(
        schema_version=HANDOFF_SCHEMA_VERSION,
        created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        repository=repository,
        changes=changes,
        recent_commits=recent_commits,
        semantic=SemanticSection(
            goal="TODO: describe the current goal",
            current_scope="TODO: describe what is in scope for this session",
        ),
        next_action=NextAction(
            task="TODO: define the single next concrete task",
            success_condition="TODO: define one concrete, checkable success condition",
        ),
    )

    json_path, md_path = handoff_paths(root)
    ensure_dir(json_path.parent)
    atomic_write_text(json_path, handoff.model_dump_json(indent=2) + "\n")
    atomic_write_text(md_path, render_handoff_markdown(handoff))

    return handoff


def _load_recorded_handoff(json_path: Path) -> tuple[Handoff | None, DriftItem | None]:
    """Load and validate a recorded checkpoint. Returns (handoff, None) on success,
    or (None, blocking DriftItem) describing exactly why it could not be used."""
    if not json_path.exists():
        return None, DriftItem(
            field="handoff",
            severity=Severity.BLOCKING,
            message=f"No checkpoint found at {json_path}. Run `repoops checkpoint .` first.",
        )

    raw_text = json_path.read_text(encoding="utf-8")
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, DriftItem(
            field="handoff_schema",
            severity=Severity.BLOCKING,
            message=f"{json_path} is not valid JSON: {exc}",
        )

    recorded_version = raw.get("schema_version") if isinstance(raw, dict) else None
    if recorded_version != HANDOFF_SCHEMA_VERSION:
        return None, DriftItem(
            field="handoff_schema",
            severity=Severity.BLOCKING,
            message=(
                f"Unsupported handoff schema version: got {recorded_version!r}, "
                f"expected {HANDOFF_SCHEMA_VERSION!r}."
            ),
        )

    try:
        recorded = Handoff.model_validate(raw)
    except ValidationError as exc:
        return None, DriftItem(
            field="handoff_schema",
            severity=Severity.BLOCKING,
            message=f"{json_path} failed schema validation: {exc}",
        )

    return recorded, None


def _counts_diff_message(old: ChangeCounts, new: ChangeCounts) -> str:
    parts = []
    for name in ("staged", "modified", "untracked", "deleted", "renamed", "conflicted"):
        old_value = getattr(old, name)
        new_value = getattr(new, name)
        if old_value != new_value:
            parts.append(f"{name}: {old_value} -> {new_value}")
    return ", ".join(parts)


def _compute_drift(
    recorded: Handoff, current_repository: RepositoryInfo, current_changes: ChangesInfo
) -> list[DriftItem]:
    items: list[DriftItem] = []
    old_repo = recorded.repository

    if old_repo.root != current_repository.root:
        items.append(
            DriftItem(
                field="repository_root",
                severity=Severity.BLOCKING,
                message="The repository root does not match the recorded checkpoint.",
                old=old_repo.root,
                new=current_repository.root,
            )
        )

    if old_repo.branch != current_repository.branch:
        items.append(
            DriftItem(
                field="branch",
                severity=Severity.BLOCKING,
                message="The current branch has changed since the checkpoint was recorded.",
                old=old_repo.branch or "(detached)",
                new=current_repository.branch or "(detached)",
            )
        )

    if old_repo.detached_head != current_repository.detached_head:
        items.append(
            DriftItem(
                field="detached_head",
                severity=Severity.WARNING,
                message="Detached-HEAD state has changed since the checkpoint was recorded.",
                old=str(old_repo.detached_head),
                new=str(current_repository.detached_head),
            )
        )

    if old_repo.head_full != current_repository.head_full:
        items.append(
            DriftItem(
                field="head",
                severity=Severity.WARNING,
                message="HEAD has moved since the checkpoint was recorded.",
                old=old_repo.head_short,
                new=current_repository.head_short,
            )
        )

    counts_changed = recorded.changes.counts != current_changes.counts
    if old_repo.dirty != current_repository.dirty or counts_changed:
        counts_message = _counts_diff_message(recorded.changes.counts, current_changes.counts)
        message = "Worktree state has changed since the checkpoint was recorded."
        if counts_message:
            message += f" ({counts_message})"
        items.append(
            DriftItem(
                field="worktree_state",
                severity=Severity.WARNING,
                message=message,
                old=str(old_repo.dirty),
                new=str(current_repository.dirty),
            )
        )

    return items


def run_resume(path: str | Path) -> ResumeReport:
    """Compare the recorded checkpoint against current repository state.

    Read-only: never modifies `.repoops/handoff.json`, `.repoops/HANDOFF.md`, or
    any other repository state.
    """
    root = discover_repo_root(path)
    current_repository, current_changes, current_recent_commits = collect_repository_facts(root)

    json_path, _ = handoff_paths(root)
    recorded, load_error = _load_recorded_handoff(json_path)

    if load_error is not None:
        drift_items = [load_error]
    else:
        assert recorded is not None
        drift_items = _compute_drift(recorded, current_repository, current_changes)

    overall_severity = Severity.NONE
    for item in drift_items:
        if item.severity == Severity.BLOCKING:
            overall_severity = Severity.BLOCKING
            break
        if item.severity == Severity.WARNING and overall_severity == Severity.NONE:
            overall_severity = Severity.WARNING

    return ResumeReport(
        recorded=recorded,
        current_repository=current_repository,
        current_changes=current_changes,
        current_recent_commits=current_recent_commits,
        drift_items=drift_items,
        overall_severity=overall_severity,
    )
