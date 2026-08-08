"""Provider-neutral agent execution: `AgentRunner.run(task, repo, config) -> AgentRunResult`.

`AntigravityRunner` is the only implementation today, driving the official `agy`
CLI as a subprocess and consuming its `stream-json` NDJSON output incrementally.
Nothing here automates a GUI, extracts tokens, or impersonates a provider API --
it only spawns the documented headless `agy` invocation and reads its stdout.

Git evidence is captured independently of anything the agent reports, reusing
the same whitelisted, stat-only Git primitives as `repoops.git_scan` /
`repoops.handoff` (`_run_git`, `parse_porcelain_status`, `redact_diff_stat`,
`redact_secret_like_path`). No new Git commands are introduced. This module
never runs `git add`/`commit`/`push`/`reset`/`clean`/`stash`, and never
automatically starts a second task.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from repoops import agy_cli
from repoops.agent_models import (
    AGENT_REPORT_JSON_SCHEMA,
    AgentReport,
    AgentRunConfig,
    AgentRunResult,
    GitEvidence,
    MalformedEvent,
    ToolStep,
)
from repoops.git_scan import (
    PorcelainSummary,
    _run_git,
    parse_porcelain_status,
    redact_secret_like_path,
)
from repoops.handoff import _filter_handoff_dir_from_status, redact_diff_stat
from repoops.paths import ensure_dir
from repoops.progress import ProgressCallback

AGENT_RUNS_DIRNAME = ".repoops/agent-runs"

_STATUS_ARGS: tuple[str, ...] = ("status", "--porcelain=v1")
_DIFF_STAT_ARGS: tuple[str, ...] = ("diff", "--stat")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _spawn_agy(argv: list[str], *, cwd: Path) -> subprocess.Popen:
    """Spawn the `agy` subprocess. Isolated from `git_scan`'s own `subprocess.run`
    calls so tests can substitute this one launch point without also intercepting
    read-only Git evidence collection."""
    return subprocess.Popen(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def capture_git_state(repo_root: Path) -> PorcelainSummary:
    """Snapshot current worktree status via the whitelisted, read-only `_run_git`.

    Excludes `.repoops/` (RepoOps' own bookkeeping directory, e.g. this run's
    `agent-runs/<run_id>/` record) using the same filter `repoops checkpoint`
    already applies -- otherwise every run would show a false-positive "changed
    file" for its own run record.
    """
    status_result = _run_git(repo_root, _STATUS_ARGS)
    filtered = _filter_handoff_dir_from_status(status_result.stdout)
    return parse_porcelain_status(filtered)


def diff_git_evidence(
    repo_root: Path, before: PorcelainSummary, after: PorcelainSummary
) -> GitEvidence:
    """Derive deterministic Git evidence from independently captured before/after status.

    Never trusts the agent's own claim about which files changed.
    """
    before_paths = {entry.path: entry.code for entry in before.entries}
    after_paths = {entry.path: entry.code for entry in after.entries}

    added_files = sorted(p for p in after_paths if p not in before_paths)
    deleted_files = sorted(p for p, code in after_paths.items() if "D" in code)
    changed_files = sorted(p for p, code in after_paths.items() if before_paths.get(p) != code)

    diff_stat = redact_diff_stat(_run_git(repo_root, _DIFF_STAT_ARGS).stdout)

    return GitEvidence(
        before_entries=sorted(redact_secret_like_path(p) for p in before_paths),
        after_entries=sorted(redact_secret_like_path(p) for p in after_paths),
        changed_files=[redact_secret_like_path(p) for p in changed_files],
        added_files=[redact_secret_like_path(p) for p in added_files],
        deleted_files=[redact_secret_like_path(p) for p in deleted_files],
        diff_stat=diff_stat,
        before_dirty=before.dirty,
        after_dirty=after.dirty,
    )


class AgentRunner(ABC):
    """Provider-neutral runner interface. A future `CodexRunner` implements this
    same contract without changing task semantics."""

    provider: str

    @abstractmethod
    def run(
        self,
        *,
        task: str,
        repo: Path,
        config: AgentRunConfig,
        on_progress: ProgressCallback | None = None,
    ) -> AgentRunResult:
        """Execute one task in `repo` and return a normalized, persisted result."""


@dataclass
class _RunState:
    steps: list[ToolStep] = field(default_factory=list)
    commands_executed: list[str] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)
    malformed_events: list[MalformedEvent] = field(default_factory=list)
    session_id: str | None = None
    resolved_model: str | None = None
    usage: dict | None = None
    agent_report: AgentReport | None = None


def _consume_event(event: dict, state: _RunState) -> None:
    """Normalize one parsed `stream-json` event into `state`. Unknown event types
    are recorded as an observable step but otherwise ignored -- no hidden
    chain-of-thought is extracted or reconstructed.

    Real `agy` events are enveloped as `{"event": "<type>", "<type>": {...},
    "conversation_id"?: ...}` -- the payload lives under a key matching the
    event type, not flat on the event itself. `conversation_id` is a top-level
    sibling on `init` but nested inside the payload on `step_update`/`result`.
    There is no distinct `tool_error` event type: a failed tool call surfaces
    as unstructured text inside `tool_info.output`, and a fatal run only
    surfaces as `result.status == "ERROR"` with a `result.error` string (also
    reflected in a non-zero process exit code).
    """
    event_type = event.get("event", "unknown")
    payload = event.get(event_type)
    if not isinstance(payload, dict):
        payload = {}

    conversation_id = payload.get("conversation_id") or event.get("conversation_id")
    if conversation_id:
        state.session_id = conversation_id

    if event_type == "init":
        state.resolved_model = payload.get("model") or state.resolved_model
        state.steps.append(ToolStep(index=len(state.steps), type=event_type, raw=event))
        return

    if event_type == "step_update":
        tool_info = payload.get("tool_info") or {}
        command = None
        if tool_info.get("name") == "run_command":
            command = (tool_info.get("parameters") or {}).get("CommandLine")
        step = ToolStep(
            index=len(state.steps),
            type=event_type,
            tool=payload.get("tool_name"),
            command=command,
            status=payload.get("state"),
            error=None,
            raw=event,
        )
        state.steps.append(step)
        if command:
            state.commands_executed.append(command)
        return

    if event_type == "result":
        state.usage = payload.get("usage") or state.usage
        if payload.get("status") == "ERROR":
            error_message = payload.get("error") or "agy reported an ERROR result with no detail"
            state.tool_errors.append(error_message)
        structured = payload.get("structured_output")
        if isinstance(structured, dict):
            try:
                state.agent_report = AgentReport.model_validate(structured)
            except ValidationError as exc:
                state.malformed_events.append(
                    MalformedEvent(
                        line_number=len(state.steps) + 1,
                        raw_text=json.dumps(structured)[:500],
                        error=f"structured_output failed schema validation: {exc}",
                    )
                )
        state.steps.append(ToolStep(index=len(state.steps), type=event_type, raw=event))
        return

    state.steps.append(ToolStep(index=len(state.steps), type=event_type, raw=event))


class AntigravityRunner(AgentRunner):
    """Drives the official `agy` CLI headlessly and normalizes its `stream-json` output."""

    provider = "antigravity"

    def __init__(self, agy_path: str | None = None) -> None:
        self._agy_path_override = agy_path

    def run(
        self,
        *,
        task: str,
        repo: Path,
        config: AgentRunConfig,
        on_progress: ProgressCallback | None = None,
    ) -> AgentRunResult:
        agy_path = self._agy_path_override or agy_cli.require_agy()
        repo_root = Path(repo).expanduser().resolve()

        # Captured before creating our own .repoops/agent-runs/<run_id>/ bookkeeping
        # directory, so "before" evidence reflects the caller's actual repo state
        # and isn't polluted by RepoOps' own untracked run record.
        before = capture_git_state(repo_root)

        run_id = uuid.uuid4().hex
        run_dir = ensure_dir(repo_root / AGENT_RUNS_DIRNAME / run_id)
        raw_log_path = run_dir / "stream.ndjson"
        schema_path = run_dir / "report.schema.json"
        schema_path.write_text(
            json.dumps(AGENT_REPORT_JSON_SCHEMA, indent=2) + "\n", encoding="utf-8"
        )

        started_at = _now_iso()

        if on_progress:
            on_progress("agent", f'started provider={self.provider} model="{config.model}"')

        argv = agy_cli.build_agy_argv(
            agy_path,
            model=config.model,
            schema_path=schema_path,
            prompt=task,
            extra_args=config.extra_args,
        )

        state = _RunState()
        exit_code: int
        process_status: str
        stderr_text = ""

        try:
            proc = _spawn_agy(argv, cwd=repo_root)
        except OSError as exc:
            ended_at = _now_iso()
            if on_progress:
                on_progress("agent", f"process failure: {exc}")
            after = capture_git_state(repo_root)
            git_evidence = diff_git_evidence(repo_root, before, after)
            result = AgentRunResult(
                run_id=run_id,
                provider=self.provider,
                requested_model=config.model,
                resolved_model=None,
                session_id=None,
                repository=str(repo_root),
                started_at=started_at,
                ended_at=ended_at,
                exit_code=-1,
                process_status="spawn_failed",
                agent_report=None,
                steps=[],
                commands_executed=[],
                tool_errors=[str(exc)],
                usage=None,
                malformed_events=[],
                git_evidence=git_evidence,
                process_exit_status="failed",
                verification_notes=[f"Failed to start '{agy_path}': {exc}"],
                raw_event_log_path=str(raw_log_path),
                run_dir=str(run_dir),
            )
            raw_log_path.write_text("", encoding="utf-8")
            self._persist(run_dir, result)
            return result

        timed_out = False
        start_time = time.monotonic()

        assert proc.stdout is not None
        with raw_log_path.open("w", encoding="utf-8") as raw_log:
            for line_number, line in enumerate(proc.stdout, start=1):
                raw_log.write(line)
                if (
                    config.timeout_seconds
                    and (time.monotonic() - start_time) > config.timeout_seconds
                ):
                    timed_out = True
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    state.malformed_events.append(
                        MalformedEvent(
                            line_number=line_number, raw_text=stripped[:500], error=str(exc)
                        )
                    )
                    continue
                if not isinstance(event, dict):
                    state.malformed_events.append(
                        MalformedEvent(
                            line_number=line_number,
                            raw_text=stripped[:500],
                            error="Top-level NDJSON event is not a JSON object.",
                        )
                    )
                    continue
                _consume_event(event, state)

        stderr_text = proc.stderr.read() if proc.stderr else ""

        if not timed_out:
            remaining_timeout = None
            if config.timeout_seconds:
                elapsed = time.monotonic() - start_time
                remaining_timeout = max(0.1, config.timeout_seconds - elapsed)
            try:
                exit_code = proc.wait(timeout=remaining_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True

        if timed_out:
            process_status = "timed_out"
            exit_code = -1
            process_exit_status = "failed"
            if on_progress:
                on_progress("agent", f"timed out after {config.timeout_seconds}s")
            if hasattr(proc, "terminate"):
                with contextlib.suppress(Exception):
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except Exception:
                        if hasattr(proc, "kill"):
                            proc.kill()
        else:
            process_status = "completed"
            process_exit_status = "success" if exit_code == 0 else "failed"
            if on_progress:
                on_progress("agent", f"completed exit={exit_code}")

        ended_at = _now_iso()

        after = capture_git_state(repo_root)
        git_evidence = diff_git_evidence(repo_root, before, after)

        verification_notes: list[str] = []
        if timed_out:
            verification_notes.append(
                f"Agent process execution timed out after {config.timeout_seconds} seconds."
            )
        elif exit_code != 0:
            note = f"agy exited with code {exit_code}."
            if stderr_text.strip():
                note += f" stderr: {stderr_text.strip()[:500]}"
            verification_notes.append(note)
        if (
            not timed_out
            and state.agent_report is not None
            and state.agent_report.status == "success"
            and process_exit_status != "success"
        ):
            verification_notes.append(
                "Antigravity reported status=success but the process exit code "
                "indicates failure -- treating the run as failed. Agent self-reports "
                "are never treated as ground truth."
            )

        result = AgentRunResult(
            run_id=run_id,
            provider=self.provider,
            requested_model=config.model,
            resolved_model=state.resolved_model,
            session_id=state.session_id,
            repository=str(repo_root),
            started_at=started_at,
            ended_at=ended_at,
            exit_code=exit_code,
            process_status=process_status,
            agent_report=state.agent_report,
            steps=state.steps,
            commands_executed=state.commands_executed,
            tool_errors=state.tool_errors,
            usage=state.usage,
            malformed_events=state.malformed_events,
            git_evidence=git_evidence,
            process_exit_status=process_exit_status,
            verification_notes=verification_notes,
            raw_event_log_path=str(raw_log_path),
            run_dir=str(run_dir),
        )
        self._persist(run_dir, result)
        return result

    @staticmethod
    def _persist(run_dir: Path, result: AgentRunResult) -> None:
        (run_dir / "run.json").write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


def select_runner(provider: str) -> AgentRunner:
    """Resolve a provider name to an `AgentRunner`. Only 'antigravity' exists today."""
    if provider == "antigravity":
        return AntigravityRunner()
    raise ValueError(f"Unsupported agent provider: {provider!r}")
