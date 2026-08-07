"""Pydantic models and JSON Schema for `repoops agent-run` execution records.

`AgentRunResult` is the on-disk schema written to
`.repoops/agent-runs/<run_id>/run.json`. `AGENT_REPORT_JSON_SCHEMA` is handed to
`agy --json-schema` so the agent's final structured answer conforms to
`AgentReport` -- this is the agent's *self-report*, not ground truth. Ground
truth is `GitEvidence` plus `exit_code` / `repoops_verified_status`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

AGENT_RUN_SCHEMA_VERSION = "repoops.agent_run.v1"


class AgentReportStatus(StrEnum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    FAILED = "failed"


class AgentReport(BaseModel):
    """The agent's own final report. Treated as a claim, never as verified fact."""

    status: AgentReportStatus
    summary: str
    verification_reported: str | None = None
    blockers: list[str] = Field(default_factory=list)
    remaining_risks: list[str] = Field(default_factory=list)
    suggested_next_action: str | None = None


AGENT_REPORT_JSON_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "RepoOpsAgentReport",
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["success", "blocked", "failed"]},
        "summary": {"type": "string"},
        "verification_reported": {"type": ["string", "null"]},
        "blockers": {"type": "array", "items": {"type": "string"}},
        "remaining_risks": {"type": "array", "items": {"type": "string"}},
        "suggested_next_action": {"type": ["string", "null"]},
    },
    "required": ["status", "summary"],
    "additionalProperties": False,
}


class ToolStep(BaseModel):
    """One observable action step from the `stream-json` event log."""

    index: int
    type: str
    tool: str | None = None
    command: str | None = None
    status: str | None = None
    error: str | None = None
    raw: dict = Field(default_factory=dict)


class MalformedEvent(BaseModel):
    """A raw NDJSON line that failed to parse as JSON. Never fatal to the run."""

    line_number: int
    raw_text: str
    error: str


class GitEvidence(BaseModel):
    """Deterministic before/after Git evidence. Never derived from the agent's claims.

    Computed from `git status --porcelain=v1` (before/after) and `git diff --stat`
    (after) only -- the same stat-only, path-redacted primitives already used by
    `repoops scan`/`repoops checkpoint`. Never reads file contents or full diffs.
    """

    before_entries: list[str] = Field(default_factory=list)
    after_entries: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    added_files: list[str] = Field(default_factory=list)
    deleted_files: list[str] = Field(default_factory=list)
    diff_stat: str = ""
    before_dirty: bool = False
    after_dirty: bool = False


class ExpectedChanges(BaseModel):
    required: bool = True


class TaskContract(BaseModel):
    """Provider-neutral task contract defining objective, path boundaries,
    and acceptance commands."""

    id: str
    objective: str
    expected_changes: ExpectedChanges = Field(default_factory=ExpectedChanges)
    allowed_paths: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)


class AcceptanceResult(BaseModel):
    """Result of running one deterministic acceptance command after agent run finishes."""

    command: str
    started_at: str
    ended_at: str
    exit_code: int
    stdout: str
    stderr: str
    passed: bool
    timed_out: bool = False


class AgentRunConfig(BaseModel):
    """Provider-neutral run configuration, supplied by the caller (CLI/RepoOps),
    never embedded in a runner's implementation logic."""

    model: str
    extra_args: list[str] = Field(default_factory=list)
    timeout_seconds: int = 1800


class AgentRunResult(BaseModel):
    """The full, persisted record of one `AgentRunner.run(...)` execution."""

    schema_version: str = AGENT_RUN_SCHEMA_VERSION
    run_id: str
    provider: str
    requested_model: str
    resolved_model: str | None = None
    session_id: str | None = None
    repository: str
    started_at: str
    ended_at: str
    exit_code: int
    process_status: str
    agent_report: AgentReport | None = None
    steps: list[ToolStep] = Field(default_factory=list)
    commands_executed: list[str] = Field(default_factory=list)
    tool_errors: list[str] = Field(default_factory=list)
    usage: dict | None = None
    malformed_events: list[MalformedEvent] = Field(default_factory=list)
    git_evidence: GitEvidence = Field(default_factory=GitEvidence)
    # Derived solely from the `agy` exit code -- not acceptance-test verification.
    process_exit_status: str = "failed"
    verification_notes: list[str] = Field(default_factory=list)
    raw_event_log_path: str = ""
    run_dir: str = ""

    # TaskContract snapshot and verification layer results
    task_contract: TaskContract | None = None
    workspace_policy_status: str = "passed"  # "passed" | "violation"
    workspace_policy_violations: list[str] = Field(default_factory=list)
    acceptance_status: str = "skipped"  # "passed" | "failed" | "skipped"
    acceptance_results: list[AcceptanceResult] = Field(default_factory=list)
    verdict: str = "unverified"  # "verified" | "failed" | "policy_violation" | "unverified"

