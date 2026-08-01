"""Rendering for repoops handoff checkpoints and resume reports.

`render_handoff_markdown` produces `.repoops/HANDOFF.md` — readable, pasteable
into a fresh coding-agent session. `render_resume_report` produces the stdout
output of `repoops resume`, with clearly separated sections and explicit drift
severity. Neither function performs I/O or Git calls.
"""

from __future__ import annotations

from typing import Any

from repoops.handoff_models import Handoff, ResumeReport, Severity

_UNSET = "(none)"

GENERATED_FILE_NOTICE = (
    "> **Generated file -- do not hand-edit.** This file is rendered from "
    "`.repoops/handoff.json`, the canonical editable source. Edit the JSON, then run "
    "`repoops checkpoint .` to refresh this view. Manual changes made directly to this "
    "Markdown file are **not** consumed by `repoops resume` and will be silently "
    "overwritten by the next checkpoint."
)


def _optional(value: str | None) -> str:
    return value if value else _UNSET


def _list_or_none(values: list[str]) -> str:
    return ", ".join(values) if values else _UNSET


def _bulleted_or_none(values: list[str]) -> list[str]:
    """Render a list of free-text strings as Markdown bullets, one entry per line."""
    if not values:
        return [f"- {_UNSET}"]
    return [f"- {value}" for value in values]


def _format_entry(entry: dict[str, Any]) -> str:
    """Format a single freeform semantic entry (decision, failed attempt, verification)
    as `key: value` pairs, keys sorted for deterministic output regardless of the
    original dict's insertion order."""
    if not entry:
        return "(empty entry)"
    return "; ".join(f"{key}: {entry[key]}" for key in sorted(entry))


def _entries_or_none(entries: list[dict[str, Any]]) -> list[str]:
    """Render a list of freeform semantic entries as Markdown bullets."""
    if not entries:
        return [f"- {_UNSET}"]
    return [f"- {_format_entry(entry)}" for entry in entries]


def render_handoff_markdown(handoff: Handoff) -> str:
    """Render `.repoops/HANDOFF.md`: deterministic facts + the editable semantic section."""
    r = handoff.repository
    c = handoff.changes
    lines: list[str] = []

    lines.append("# repoops handoff")
    lines.append("")
    lines.append(GENERATED_FILE_NOTICE)
    lines.append("")
    lines.append(f"- Schema: `{handoff.schema_version}`")
    lines.append(f"- Created: `{handoff.created_at}`")
    lines.append("")

    lines.append("## Repository")
    lines.append("")
    lines.append(f"- Name: `{r.name}`")
    lines.append(f"- Root: `{r.root}`")
    lines.append(f"- Remote identity: `{r.remote_identity or _UNSET}`")
    lines.append(f"- Branch: `{r.branch or '(detached)'}`")
    lines.append(f"- Detached HEAD: `{r.detached_head}`")
    lines.append(f"- HEAD: `{r.head_short}` (`{r.head_full}`)")
    lines.append(f"- Upstream: `{r.upstream or '(none)'}`")
    lines.append(f"- Ahead: `{r.ahead if r.ahead is not None else '-'}`")
    lines.append(f"- Behind: `{r.behind if r.behind is not None else '-'}`")
    lines.append(f"- Dirty: `{r.dirty}`")
    lines.append("")

    lines.append("## Changes")
    lines.append("")
    lines.append(
        "- Counts: "
        f"staged=`{c.counts.staged}`, modified=`{c.counts.modified}`, "
        f"untracked=`{c.counts.untracked}`, deleted=`{c.counts.deleted}`, "
        f"renamed=`{c.counts.renamed}`, conflicted=`{c.counts.conflicted}`"
    )
    if c.notable_paths:
        lines.append("- Notable paths:")
        lines.extend(f"  - `{p}`" for p in c.notable_paths)
    else:
        lines.append("- Notable paths: (none)")
    lines.append("")

    lines.append("### `git diff --stat`")
    lines.append("")
    lines.append("```text")
    lines.append(c.diff_stat if c.diff_stat.strip() else "(no unstaged changes)")
    lines.append("```")
    lines.append("")

    lines.append("### `git diff --cached --stat`")
    lines.append("")
    lines.append("```text")
    lines.append(c.cached_diff_stat if c.cached_diff_stat.strip() else "(no staged changes)")
    lines.append("```")
    lines.append("")

    lines.append("## Recent commits")
    lines.append("")
    if handoff.recent_commits:
        for commit in handoff.recent_commits:
            lines.append(f"- `{commit.short_hash}` {commit.date} — {commit.subject}")
    else:
        lines.append("(no commits found)")
    lines.append("")

    s = handoff.semantic
    lines.append("## Semantic notes")
    lines.append("")
    lines.append(
        "(Editable in `.repoops/handoff.json` only -- see the notice at the top of this file.)"
    )
    lines.append("")
    lines.append(f"- Goal: {s.goal or _UNSET}")
    lines.append(f"- Current scope: {s.current_scope or _UNSET}")
    lines.append("")

    lines.append("### Out of scope")
    lines.append("")
    lines.extend(_bulleted_or_none(s.out_of_scope))
    lines.append("")

    lines.append("### Completed")
    lines.append("")
    lines.extend(_bulleted_or_none(s.completed))
    lines.append("")

    lines.append("### Decisions")
    lines.append("")
    lines.extend(_entries_or_none(s.decisions))
    lines.append("")

    lines.append("### Failed attempts")
    lines.append("")
    lines.extend(_entries_or_none(s.failed_attempts))
    lines.append("")

    lines.append("### Verification passed")
    lines.append("")
    lines.extend(_entries_or_none(s.verification_passed))
    lines.append("")

    lines.append("### Verification pending")
    lines.append("")
    lines.extend(_entries_or_none(s.verification_pending))
    lines.append("")

    n = handoff.next_action
    lines.append("## Next action")
    lines.append("")
    lines.append(f"- Task: {n.task or _UNSET}")
    lines.append(f"- Command: {_optional(n.command)}")
    lines.append(f"- Success condition: {n.success_condition or _UNSET}")
    lines.append(f"- Blocker: {_optional(n.blocker)}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "Paste this file (or `.repoops/handoff.json`) into a fresh coding-agent session "
        "to continue this work. Run `repoops resume .` first to confirm nothing has "
        "drifted since this checkpoint was recorded."
    )

    return "\n".join(lines).rstrip() + "\n"


def render_resume_report(report: ResumeReport) -> str:
    """Render the stdout output of `repoops resume`, with explicit drift severity.

    Never claims it is safe to continue when meaningful (WARNING or BLOCKING) drift
    was detected.
    """
    lines: list[str] = []

    lines.append("=== RECORDED HANDOFF ===")
    lines.append("")
    if report.recorded is None:
        lines.append("(none — no valid checkpoint could be loaded for this repository)")
    else:
        rr = report.recorded.repository
        s = report.recorded.semantic
        lines.append(f"Schema: {report.recorded.schema_version}")
        lines.append(f"Created: {report.recorded.created_at}")
        lines.append(f"Repository root: {rr.root}")
        lines.append(f"Remote identity: {rr.remote_identity or _UNSET}")
        lines.append(f"Branch: {rr.branch or '(detached)'}")
        lines.append(f"HEAD: {rr.head_short} ({rr.head_full})")
        lines.append(f"Dirty: {rr.dirty}")
        lines.append("")
        lines.append(f"Goal: {s.goal or _UNSET}")
        lines.append(f"Current scope: {s.current_scope or _UNSET}")
        lines.append(f"Out of scope: {_list_or_none(s.out_of_scope)}")
        lines.append(f"Completed: {_list_or_none(s.completed)}")
        lines.append("Decisions:")
        lines.extend(f"  {entry}" for entry in _entries_or_none(s.decisions))
        lines.append("Failed attempts:")
        lines.extend(f"  {entry}" for entry in _entries_or_none(s.failed_attempts))
        lines.append("Verification passed:")
        lines.extend(f"  {entry}" for entry in _entries_or_none(s.verification_passed))
        lines.append("Verification pending:")
        lines.extend(f"  {entry}" for entry in _entries_or_none(s.verification_pending))
    lines.append("")

    lines.append("=== CURRENT REPOSITORY STATE ===")
    lines.append("")
    cr = report.current_repository
    cc = report.current_changes
    lines.append(f"Repository root: {cr.root}")
    lines.append(f"Remote identity: {cr.remote_identity or _UNSET}")
    lines.append(f"Branch: {cr.branch or '(detached)'}")
    lines.append(f"HEAD: {cr.head_short} ({cr.head_full})")
    lines.append(f"Dirty: {cr.dirty}")
    lines.append(
        "Counts: "
        f"staged={cc.counts.staged}, modified={cc.counts.modified}, "
        f"untracked={cc.counts.untracked}, deleted={cc.counts.deleted}, "
        f"renamed={cc.counts.renamed}, conflicted={cc.counts.conflicted}"
    )
    lines.append("")

    lines.append(f"=== DRIFT DETECTED (overall severity: {report.overall_severity}) ===")
    lines.append("")
    if not report.drift_items:
        lines.append("NONE — current repository state matches the recorded checkpoint.")
    else:
        for item in report.drift_items:
            suffix = ""
            if item.old is not None or item.new is not None:
                suffix = f" (old={item.old!r}, new={item.new!r})"
            lines.append(f"[{item.severity}] {item.field}: {item.message}{suffix}")
    lines.append("")

    lines.append("=== NEXT ACTION ===")
    lines.append("")
    if report.overall_severity == Severity.BLOCKING:
        lines.append(
            "BLOCKING drift detected above — it is NOT safe to assume the recorded "
            "checkpoint still describes this repository. Resolve the drift first."
        )
        lines.append("")
    elif report.overall_severity == Severity.WARNING:
        lines.append(
            "WARNING drift detected above — review it before continuing from the "
            "recorded checkpoint."
        )
        lines.append("")

    if report.recorded is None:
        lines.append(
            "Run `repoops checkpoint .` to create a checkpoint, then `repoops resume .` again."
        )
    else:
        n = report.recorded.next_action
        lines.append(f"Task: {n.task or _UNSET}")
        lines.append(f"Command: {_optional(n.command)}")
        lines.append(f"Success condition: {n.success_condition or _UNSET}")
        lines.append(f"Blocker: {_optional(n.blocker)}")

    return "\n".join(lines).rstrip() + "\n"
