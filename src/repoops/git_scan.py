"""Read-only Git scanning and risk classification."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

from repoops.config import RepoConfig, RepoOpsConfig

SNAPSHOT_SCHEMA_VERSION = "repoops.snapshot.v1"

# Only these exact read-only, metadata-only argument tuples may ever be run via _run_git.
ALLOWED_GIT_COMMANDS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("rev-parse", "--is-inside-work-tree"),
        ("rev-parse", "--abbrev-ref", "HEAD"),
        ("rev-parse", "--short", "HEAD"),
        ("status", "--porcelain=v1"),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"),
        ("rev-list", "--count", "@{u}..HEAD"),
        ("rev-list", "--count", "HEAD..@{u}"),
        # The five below are used only by repoops.handoff (`repoops checkpoint`/`repoops
        # resume`). All are read-only and metadata/stat-only — `diff --stat` and
        # `diff --cached --stat` report changed filenames and line counts, never file
        # contents or full diffs; `log` is capped at a fixed 5-commit limit.
        ("rev-parse", "--show-toplevel"),
        ("rev-parse", "HEAD"),
        ("diff", "--stat"),
        ("diff", "--cached", "--stat"),
        ("log", "-5", "--pretty=format:%h\x1f%ad\x1f%s", "--date=iso-strict"),
    }
)

# `git fetch` is kept in a separate whitelist and separate runner from _run_git: it is the
# only command in this module that touches the network, so it must never be reachable by
# broadening ALLOWED_GIT_COMMANDS alone.
ALLOWED_FETCH_COMMANDS: frozenset[tuple[str, ...]] = frozenset({("fetch", "--prune")})

CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}

RiskFlag = Literal[
    "dirty",
    "staged_changes",
    "deleted_files",
    "many_changes",
    "untracked_files",
    "possible_secret_file",
    "dependency_file_changed",
    "ci_file_changed",
    "notebook_changed",
    "repo_missing",
    "not_git_repo",
    "detached_head",
    "ahead_remote",
    "behind_remote",
    "diverged_remote",
    "no_upstream",
    "fetch_failed",
]

ATTENTION_POINTS: dict[str, int] = {
    "repo_missing": 100,
    "not_git_repo": 90,
    "possible_secret_file": 70,
    "fetch_failed": 65,
    "deleted_files": 50,
    "diverged_remote": 45,
    "ahead_remote": 40,
    "behind_remote": 35,
    "dirty": 30,
    "many_changes": 25,
    "no_upstream": 10,
    "untracked_files": 10,
}
CONFLICTED_ATTENTION_POINTS = 80

_URL_PATTERN = re.compile(r"\S+://\S+")
_MAX_FETCH_ERROR_LENGTH = 200

SECRET_COMPONENT_MARKERS = (
    ".env",
    "secret",
    "secrets",
    "credential",
    "credentials",
    "token",
    "private",
    "id_rsa",
    "id_ed25519",
)

DEPENDENCY_FILENAMES = {
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "uv.lock",
    "poetry.lock",
    "pixi.lock",
    "environment.yml",
    "environment.yaml",
    "conda-lock.yml",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}


class ChangeCounts(BaseModel):
    modified: int = 0
    staged: int = 0
    untracked: int = 0
    deleted: int = 0
    renamed: int = 0
    conflicted: int = 0



class PorcelainEntry(BaseModel):
    code: str
    path: str
    redacted_path: str
    untracked: bool = False
    secret_like: bool = False


class PorcelainSummary(BaseModel):
    counts: ChangeCounts = Field(default_factory=ChangeCounts)
    entries: list[PorcelainEntry] = Field(default_factory=list)

    @property
    def dirty(self) -> bool:
        return bool(self.entries)


class RemoteSyncStatus(BaseModel):
    has_upstream: bool = False
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    fetched: bool = False
    fetch_error: str | None = None


class RepoSnapshot(BaseModel):
    name: str
    path: str
    exists: bool
    is_git_repo: bool
    branch: str | None = None
    head: str | None = None
    dirty: bool = False
    counts: ChangeCounts = Field(default_factory=ChangeCounts)
    notable_files: list[str] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    remote: RemoteSyncStatus = Field(default_factory=RemoteSyncStatus)
    attention_score: int = 0


class Snapshot(BaseModel):
    schema_version: str = SNAPSHOT_SCHEMA_VERSION
    machine: str
    timestamp: str
    repos: list[RepoSnapshot]


def is_secret_like_path(path: str) -> bool:
    """Return whether a relative path looks secret-like.

    This function intentionally over-flags rather than risks exposing a sensitive path.
    It inspects path names only; it never reads file contents.
    """
    lowered = path.lower()
    components = lowered.replace("\\", "/").split("/")
    for component in components:
        if component.endswith(".pem"):
            return True
        if component in {"key", "keys", "private_key", "api_key"}:
            return True
        if any(marker in component for marker in SECRET_COMPONENT_MARKERS):
            return True
    return False


def redact_secret_like_path(path: str) -> str:
    """Redact secret-like path components while preserving non-sensitive context."""
    parts = path.replace("\\", "/").split("/")
    redacted = ["[REDACTED_SECRET_PATH]" if is_secret_like_path(part) else part for part in parts]
    return "/".join(redacted)


def _extract_path_from_porcelain(line: str) -> str:
    """Extract the path segment from a porcelain v1 line."""
    raw_path = line[3:] if len(line) > 3 else ""
    if " -> " in raw_path:
        return raw_path.split(" -> ", maxsplit=1)[1]
    return raw_path


def parse_porcelain_status(output: str) -> PorcelainSummary:
    """Parse `git status --porcelain=v1` output into counts and entries."""
    summary = PorcelainSummary()

    for raw_line in output.splitlines():
        if not raw_line:
            continue

        if raw_line.startswith("?? "):
            path = raw_line[3:]
            secret_like = is_secret_like_path(path)
            summary.counts.untracked += 1
            summary.entries.append(
                PorcelainEntry(
                    code="??",
                    path=path,
                    redacted_path=redact_secret_like_path(path) if secret_like else path,
                    untracked=True,
                    secret_like=secret_like,
                )
            )
            continue

        code = raw_line[:2]
        index_status = code[0]
        worktree_status = code[1]
        path = _extract_path_from_porcelain(raw_line)
        secret_like = is_secret_like_path(path)

        if code in CONFLICT_CODES or "U" in code:
            summary.counts.conflicted += 1
        else:
            if index_status != " ":
                summary.counts.staged += 1
            if worktree_status != " ":
                summary.counts.modified += 1
            if index_status == "D" or worktree_status == "D":
                summary.counts.deleted += 1
            if index_status == "R" or worktree_status == "R":
                summary.counts.renamed += 1

        summary.entries.append(
            PorcelainEntry(
                code=code,
                path=path,
                redacted_path=redact_secret_like_path(path) if secret_like else path,
                secret_like=secret_like,
            )
        )

    return summary


def classify_risk_flags(
    *,
    exists: bool,
    is_git_repo: bool,
    branch: str | None,
    summary: PorcelainSummary,
    many_changes_threshold: int = 20,
    remote: RemoteSyncStatus | None = None,
    remote_check: bool = True,
) -> list[RiskFlag]:
    """Classify simple v1 risk flags."""
    flags: list[RiskFlag] = []

    if not exists:
        return ["repo_missing"]
    if not is_git_repo:
        return ["not_git_repo"]

    if branch == "HEAD":
        flags.append("detached_head")

    if summary.dirty:
        flags.append("dirty")
    if summary.counts.staged > 0:
        flags.append("staged_changes")
    if summary.counts.deleted > 0:
        flags.append("deleted_files")
    if len(summary.entries) > many_changes_threshold:
        flags.append("many_changes")
    if summary.counts.untracked > 0:
        flags.append("untracked_files")
    if any(entry.secret_like for entry in summary.entries):
        flags.append("possible_secret_file")
    if any(_is_dependency_file(entry.path) for entry in summary.entries):
        flags.append("dependency_file_changed")
    if any(_is_ci_file(entry.path) for entry in summary.entries):
        flags.append("ci_file_changed")
    if any(entry.path.endswith(".ipynb") for entry in summary.entries):
        flags.append("notebook_changed")

    if remote_check and remote is not None:
        ahead = remote.ahead or 0
        behind = remote.behind or 0
        if ahead > 0:
            flags.append("ahead_remote")
        if behind > 0:
            flags.append("behind_remote")
        if ahead > 0 and behind > 0:
            flags.append("diverged_remote")
        if not remote.has_upstream:
            flags.append("no_upstream")
        if remote.fetch_error is not None:
            flags.append("fetch_failed")

    return flags


def compute_attention_score(repo_snapshot: RepoSnapshot) -> int:
    """Deterministic, pure attention score used to prioritize repos in reports."""
    score = sum(ATTENTION_POINTS.get(flag, 0) for flag in repo_snapshot.risk_flags)
    if repo_snapshot.counts.conflicted > 0:
        score += CONFLICTED_ATTENTION_POINTS
    return score


def _is_dependency_file(path: str) -> bool:
    name = Path(path).name
    if name in DEPENDENCY_FILENAMES:
        return True
    return name.startswith("requirements-") and name.endswith(".txt")


def _is_ci_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        normalized.startswith(".github/workflows/")
        or normalized == ".gitlab-ci.yml"
        or Path(normalized).name == "Jenkinsfile"
    )


def _run_git(repo_path: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Run a whitelisted, read-only Git command."""
    if args not in ALLOWED_GIT_COMMANDS:
        raise ValueError(f"Refusing to run non-whitelisted git command: git {' '.join(args)}")
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
    )


def _run_fetch(repo_path: Path, *, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    """Run the single whitelisted `git fetch --prune`. Network op; opt-in only, caller-gated."""
    args = ("fetch", "--prune")
    if args not in ALLOWED_FETCH_COMMANDS:
        raise ValueError("Refusing to run non-whitelisted fetch command")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )


def _sanitize_git_error(raw: str) -> str:
    """Reduce raw stderr to a short, credential-safe message. Safe by construction."""
    stripped = (raw or "").strip()
    first_line = stripped.splitlines()[0] if stripped else ""
    redacted = _URL_PATTERN.sub("[REDACTED_URL]", first_line)
    if not redacted:
        return "git fetch failed (no error detail captured)"
    if len(redacted) > _MAX_FETCH_ERROR_LENGTH:
        return redacted[:_MAX_FETCH_ERROR_LENGTH] + "..."
    return redacted


class _FetchOutcome(NamedTuple):
    ok: bool
    error: str | None


def _try_fetch(repo_path: Path, timeout_seconds: int) -> _FetchOutcome:
    try:
        proc = _run_fetch(repo_path, timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired:
        return _FetchOutcome(ok=False, error=f"git fetch timed out after {timeout_seconds}s")
    except OSError as exc:
        return _FetchOutcome(ok=False, error=_sanitize_git_error(str(exc)))
    if proc.returncode != 0:
        return _FetchOutcome(ok=False, error=_sanitize_git_error(proc.stderr))
    return _FetchOutcome(ok=True, error=None)


def resolve_fetch(cli_fetch: bool, config_fetch: bool) -> bool:
    """CLI --fetch can only force fetch on; it never disables a config default."""
    return cli_fetch or config_fetch


def _remote_sync_status(
    repo_path: Path,
    *,
    remote_check: bool,
    fetch: bool,
    fetch_timeout_seconds: int,
) -> RemoteSyncStatus:
    """Compute upstream/ahead/behind using local refs, optionally fetching first."""
    if not remote_check:
        return RemoteSyncStatus()

    status = RemoteSyncStatus()

    if fetch:
        outcome = _try_fetch(repo_path, fetch_timeout_seconds)
        status.fetched = outcome.ok
        status.fetch_error = outcome.error

    upstream_result = _run_git(
        repo_path, ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    )
    if upstream_result.returncode != 0 or not upstream_result.stdout.strip():
        status.has_upstream = False
        return status

    status.has_upstream = True
    status.upstream = upstream_result.stdout.strip()

    ahead_result = _run_git(repo_path, ("rev-list", "--count", "@{u}..HEAD"))
    behind_result = _run_git(repo_path, ("rev-list", "--count", "HEAD..@{u}"))
    ahead_stdout = ahead_result.stdout.strip()
    behind_stdout = behind_result.stdout.strip()
    status.ahead = (
        int(ahead_stdout) if ahead_result.returncode == 0 and ahead_stdout.isdigit() else None
    )
    status.behind = (
        int(behind_stdout) if behind_result.returncode == 0 and behind_stdout.isdigit() else None
    )
    return status


def _notable_files(
    summary: PorcelainSummary,
    *,
    max_files: int,
    include_untracked: bool,
) -> list[str]:
    notable: list[str] = []
    for entry in summary.entries:
        if entry.untracked and not include_untracked:
            continue
        notable.append(entry.redacted_path)
        if len(notable) >= max_files:
            break
    return notable


def _finalize(snapshot: RepoSnapshot) -> RepoSnapshot:
    """Compute attention_score last, once all other fields are set. RepoSnapshot is unfrozen."""
    snapshot.attention_score = compute_attention_score(snapshot)
    return snapshot


def scan_repo(
    repo: RepoConfig,
    *,
    max_files_per_repo: int = 12,
    include_untracked: bool = True,
    many_changes_threshold: int = 20,
    remote_check: bool = True,
    fetch: bool = False,
    fetch_timeout_seconds: int = 20,
) -> RepoSnapshot:
    """Scan a single repository using read-only Git commands."""
    repo_path = repo.path
    exists = repo_path.exists()
    if not exists:
        summary = PorcelainSummary()
        return _finalize(
            RepoSnapshot(
                name=repo.name,
                path=str(repo_path),
                exists=False,
                is_git_repo=False,
                risk_flags=classify_risk_flags(
                    exists=False,
                    is_git_repo=False,
                    branch=None,
                    summary=summary,
                    many_changes_threshold=many_changes_threshold,
                ),
            )
        )

    is_git_result = _run_git(repo_path, ("rev-parse", "--is-inside-work-tree"))
    is_git_repo = is_git_result.returncode == 0 and is_git_result.stdout.strip() == "true"
    if not is_git_repo:
        summary = PorcelainSummary()
        return _finalize(
            RepoSnapshot(
                name=repo.name,
                path=str(repo_path),
                exists=True,
                is_git_repo=False,
                risk_flags=classify_risk_flags(
                    exists=True,
                    is_git_repo=False,
                    branch=None,
                    summary=summary,
                    many_changes_threshold=many_changes_threshold,
                ),
            )
        )

    branch_result = _run_git(repo_path, ("rev-parse", "--abbrev-ref", "HEAD"))
    head_result = _run_git(repo_path, ("rev-parse", "--short", "HEAD"))
    status_result = _run_git(repo_path, ("status", "--porcelain=v1"))

    branch = branch_result.stdout.strip() or None
    head = head_result.stdout.strip() or None
    summary = parse_porcelain_status(status_result.stdout)
    remote = _remote_sync_status(
        repo_path,
        remote_check=remote_check,
        fetch=fetch,
        fetch_timeout_seconds=fetch_timeout_seconds,
    )

    return _finalize(
        RepoSnapshot(
            name=repo.name,
            path=str(repo_path),
            exists=True,
            is_git_repo=True,
            branch=branch,
            head=head,
            dirty=summary.dirty,
            counts=summary.counts,
            notable_files=_notable_files(
                summary,
                max_files=max_files_per_repo,
                include_untracked=include_untracked,
            ),
            risk_flags=classify_risk_flags(
                exists=True,
                is_git_repo=True,
                branch=branch,
                summary=summary,
                many_changes_threshold=many_changes_threshold,
                remote=remote,
                remote_check=remote_check,
            ),
            remote=remote,
        )
    )


def build_snapshot(config: RepoOpsConfig, *, cli_fetch: bool = False) -> Snapshot:
    """Scan all configured repositories and return a snapshot."""
    effective_fetch = resolve_fetch(cli_fetch, config.defaults.fetch)
    repos = [
        scan_repo(
            repo,
            max_files_per_repo=config.defaults.max_files_per_repo,
            include_untracked=config.defaults.include_untracked,
            many_changes_threshold=config.defaults.many_changes_threshold,
            remote_check=config.defaults.remote_check,
            fetch=effective_fetch,
            fetch_timeout_seconds=config.defaults.fetch_timeout_seconds,
        )
        for repo in config.repos
    ]
    return Snapshot(
        machine=config.machine.name,
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        repos=repos,
    )
