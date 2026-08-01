"""Pydantic/data models for the repoops handoff schema (`repoops checkpoint` / `repoops resume`).

`Handoff` is the on-disk schema written to `.repoops/handoff.json`. `DriftItem`,
`Severity`, and `ResumeReport` are in-memory only — they describe the comparison
`repoops resume` performs and are never persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from repoops.git_scan import ChangeCounts

HANDOFF_SCHEMA_VERSION = "repoops.handoff.v1"


class RepositoryInfo(BaseModel):
    name: str
    root: str
    branch: str | None = None
    detached_head: bool = False
    head_short: str = ""
    head_full: str = ""
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    dirty: bool = False


class ChangesInfo(BaseModel):
    counts: ChangeCounts = Field(default_factory=ChangeCounts)
    notable_paths: list[str] = Field(default_factory=list)
    diff_stat: str = ""
    cached_diff_stat: str = ""


class RecentCommit(BaseModel):
    short_hash: str
    date: str
    subject: str


class SemanticSection(BaseModel):
    """The human/agent-editable half of a checkpoint. Never invented by `repoops` —
    initial values are explicit `TODO:` placeholders, never asserted as fact."""

    goal: str = ""
    current_scope: str = ""
    out_of_scope: list[str] = Field(default_factory=list)
    completed: list[str] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    failed_attempts: list[dict[str, Any]] = Field(default_factory=list)
    verification_passed: list[dict[str, Any]] = Field(default_factory=list)
    verification_pending: list[dict[str, Any]] = Field(default_factory=list)


class NextAction(BaseModel):
    task: str = ""
    command: str | None = None
    success_condition: str = ""
    blocker: str | None = None


class Handoff(BaseModel):
    schema_version: str = HANDOFF_SCHEMA_VERSION
    created_at: str
    repository: RepositoryInfo
    changes: ChangesInfo
    recent_commits: list[RecentCommit] = Field(default_factory=list)
    semantic: SemanticSection = Field(default_factory=SemanticSection)
    next_action: NextAction = Field(default_factory=NextAction)


class Severity(StrEnum):
    """Resume drift severity. Ordering (for computing an overall severity) is
    NONE < WARNING < BLOCKING — see `SEVERITY_ORDER`."""

    NONE = "NONE"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


SEVERITY_ORDER: dict[Severity, int] = {
    Severity.NONE: 0,
    Severity.WARNING: 1,
    Severity.BLOCKING: 2,
}


@dataclass
class DriftItem:
    field: str
    severity: Severity
    message: str
    old: str | None = None
    new: str | None = None


@dataclass
class ResumeReport:
    recorded: Handoff | None
    current_repository: RepositoryInfo
    current_changes: ChangesInfo
    current_recent_commits: list[RecentCommit] = field(default_factory=list)
    drift_items: list[DriftItem] = field(default_factory=list)
    overall_severity: Severity = Severity.NONE

    @property
    def exit_code(self) -> int:
        return 1 if self.overall_severity == Severity.BLOCKING else 0
