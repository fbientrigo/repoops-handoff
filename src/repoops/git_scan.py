"""Read-only Git scanning and risk classification."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from repoops.config import RepoConfig, RepoOpsConfig

SNAPSHOT_SCHEMA_VERSION = "repoops.snapshot.v0"

ALLOWED_GIT_COMMANDS: set[tuple[str, ...]] = {
    ("rev-parse", "--is-inside-work-tree"),
    ("rev-parse", "--abbrev-ref", "HEAD"),
    ("rev-parse", "--short", "HEAD"),
    ("status", "--porcelain=v1"),
}

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
]

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

    @property
    def total(self) -> int:
        """Approximate total count used for human display."""
        return (
            self.modified
            + self.staged
            + self.untracked
            + self.deleted
            + self.renamed
            + self.conflicted
        )


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
) -> list[RiskFlag]:
    """Classify simple v0 risk flags."""
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

    return flags


def _is_dependency_file(path: str) -> bool:
    name = Path(path).name
    return name in DEPENDENCY_FILENAMES or name.startswith("requirements-") and name.endswith(".txt")


def _is_ci_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        normalized.startswith(".github/workflows/")
        or normalized == ".gitlab-ci.yml"
        or Path(normalized).name == "Jenkinsfile"
    )


def _run_git(repo_path: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Run an allow-listed read-only Git command."""
    if args not in ALLOWED_GIT_COMMANDS:
        raise ValueError(f"Forbidden git command attempted: git {' '.join(args)}")

    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
    )


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


def scan_repo(
    repo: RepoConfig,
    *,
    max_files_per_repo: int = 12,
    include_untracked: bool = True,
    many_changes_threshold: int = 20,
) -> RepoSnapshot:
    """Scan a single repository using read-only Git commands."""
    repo_path = repo.path
    exists = repo_path.exists()
    if not exists:
        summary = PorcelainSummary()
        return RepoSnapshot(
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

    is_git_result = _run_git(repo_path, ("rev-parse", "--is-inside-work-tree"))
    is_git_repo = is_git_result.returncode == 0 and is_git_result.stdout.strip() == "true"
    if not is_git_repo:
        summary = PorcelainSummary()
        return RepoSnapshot(
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

    branch_result = _run_git(repo_path, ("rev-parse", "--abbrev-ref", "HEAD"))
    head_result = _run_git(repo_path, ("rev-parse", "--short", "HEAD"))
    status_result = _run_git(repo_path, ("status", "--porcelain=v1"))

    branch = branch_result.stdout.strip() or None
    head = head_result.stdout.strip() or None
    summary = parse_porcelain_status(status_result.stdout)

    return RepoSnapshot(
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
        ),
    )


def build_snapshot(config: RepoOpsConfig) -> Snapshot:
    """Scan all configured repositories and return a snapshot."""
    repos = [
        scan_repo(
            repo,
            max_files_per_repo=config.defaults.max_files_per_repo,
            include_untracked=config.defaults.include_untracked,
            many_changes_threshold=config.defaults.many_changes_threshold,
        )
        for repo in config.repos
    ]
    return Snapshot(
        machine=config.machine.name,
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        repos=repos,
    )
