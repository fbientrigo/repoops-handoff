"""Typer CLI for repoops."""

import importlib.metadata
from pathlib import Path

import typer

from repoops.agent_models import AgentRunConfig, ExpectedChanges, TaskContract
from repoops.agent_runner import select_runner
from repoops.agent_verification import run_verified_task
from repoops.agy_cli import AgyError, AgyNotFoundError, AgyVersionError
from repoops.config import ConfigError, filter_config, load_config
from repoops.git_scan import build_snapshot
from repoops.handoff import (
    HandoffError,
    create_checkpoint,
    discover_repo_root,
    handoff_paths,
    run_resume,
)
from repoops.handoff_render import render_resume_report
from repoops.notify import notify_report
from repoops.paths import ensure_dir
from repoops.report import print_summary_table, print_worklog_candidates, render_markdown
from repoops.scheduler import run_scheduler_once
from repoops.task_backlog import (
    TaskBacklogError,
    TaskLockedError,
    ensure_integration_branch,
    load_backlog,
    run_next_task,
    select_next_task,
)
from repoops.task_contract import TaskContractError, load_task_contract
from repoops.worklog import (
    compute_candidates,
    iso_week_range,
    month_range,
    open_store,
    record_snapshot,
    write_candidates_csv,
)

app = typer.Typer(help="Low-noise multi-repository status and coding-agent handoff CLI.")


FETCH_OPTION_HELP = (
    "Force a safe `git fetch --prune` before computing ahead/behind status. "
    "Updates remote-tracking refs only — never the working tree, never pulls or pushes."
)

CONFIG_OPTION = typer.Option(None, "--config", "-c", help="Path to repoops YAML config.")
PROJECT_OPTION = typer.Option(None, "--project", help="Filter repositories by project name.")
TAG_OPTION = typer.Option(None, "--tag", help="Filter repositories by tag (repeatable).")


def version_callback(value: bool) -> None:
    if value:
        try:
            ver = importlib.metadata.version("repoops-handoff")
        except importlib.metadata.PackageNotFoundError:
            ver = "0.1.0"
        typer.echo(f"repoops {ver}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Low-noise multi-repository status reporter."""
    pass


@app.command()
def scan(
    config: Path | None = CONFIG_OPTION,
    project: str | None = PROJECT_OPTION,
    tag: list[str] | None = TAG_OPTION,
    fetch: bool = typer.Option(False, "--fetch", help=FETCH_OPTION_HELP),
) -> None:
    """Scan configured repositories and print a terminal table."""
    try:
        cfg = load_config(config)
        cfg = filter_config(cfg, project=project, tags=tag)
    except (ConfigError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    snapshot = build_snapshot(cfg, cli_fetch=fetch)
    print_summary_table(snapshot)


@app.command()
def run(
    config: Path | None = CONFIG_OPTION,
    project: str | None = PROJECT_OPTION,
    tag: list[str] | None = TAG_OPTION,
    fetch: bool = typer.Option(False, "--fetch", help=FETCH_OPTION_HELP),
) -> None:
    """Scan configured repositories and write JSON + Markdown artifacts."""
    try:
        cfg = load_config(config)
        cfg = filter_config(cfg, project=project, tags=tag)
    except (ConfigError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    snapshot = build_snapshot(cfg, cli_fetch=fetch)
    print_summary_table(snapshot)

    report_dir = ensure_dir(cfg.defaults.report_dir)
    snapshot_dir = ensure_dir(cfg.defaults.snapshot_dir)
    stamp = snapshot.timestamp.replace(":", "").replace("-", "").replace("T", "-").split("+")[0]

    snapshot_path = snapshot_dir / f"repoops-snapshot-{stamp}.json"
    report_path = report_dir / f"repoops-report-{stamp}.md"

    snapshot_path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    report_path.write_text(
        render_markdown(snapshot, include_clean_repos=cfg.defaults.include_clean_repos),
        encoding="utf-8",
    )

    typer.echo(f"Snapshot: {snapshot_path}")
    typer.echo(f"Report: {report_path}")

    if cfg.notifications.enabled:
        result = notify_report(cfg, report_path)
        typer.echo(f"Notification: {result.status} ({result.reason or result.channel})")


@app.command(name="notify")
def notify_cmd(
    config: Path | None = CONFIG_OPTION,
    report: Path = typer.Option(..., "--report", "-r", help="Path to an existing Markdown report."),
) -> None:
    """Send or no-op an existing report according to config."""
    try:
        cfg = load_config(config)
    except (ConfigError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    result = notify_report(cfg, report)
    typer.echo(f"Notification: {result.status} ({result.reason or result.channel})")


@app.command()
def checkpoint(
    path: Path = typer.Argument(
        Path("."), help="Path inside the Git repository to checkpoint. Defaults to '.'."
    ),
    reset_semantic: bool = typer.Option(
        False,
        "--reset-semantic",
        help=(
            "Discard any existing semantic notes and next action, replacing them with "
            "TODO placeholders. Destructive -- without this flag, a repeat checkpoint "
            "preserves existing semantic content instead."
        ),
    ),
) -> None:
    """Write a deterministic handoff checkpoint (.repoops/handoff.json + HANDOFF.md).

    Repeated runs refresh deterministic Git facts (branch, HEAD, worktree, remote, diff
    stats, recent commits, timestamp) while preserving prior semantic notes and the next
    action, unless `--reset-semantic` is given.
    """
    try:
        handoff = create_checkpoint(path, reset_semantic=reset_semantic)
    except HandoffError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    json_path, md_path = handoff_paths(Path(handoff.repository.root))
    typer.echo(f"Checkpoint written: {json_path}")
    typer.echo(f"Handoff markdown: {md_path}")


@app.command()
def resume(
    path: Path = typer.Argument(
        Path("."), help="Path inside the Git repository to resume. Defaults to '.'."
    ),
) -> None:
    """Compare current repository state against the recorded checkpoint and print
    a continuation report. Read-only: never modifies the checkpoint."""
    try:
        report = run_resume(path)
    except HandoffError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(render_resume_report(report))
    raise typer.Exit(code=report.exit_code)


@app.command(name="agent-run")
def agent_run(
    repo: Path = typer.Argument(
        ..., help="Path inside the local Git repository to run the task in."
    ),
    provider: str = typer.Option(
        "antigravity", "--provider", help="Agent provider to use. Only 'antigravity' is supported."
    ),
    model: str = typer.Option(
        ..., "--model", help="Model identifier, as returned by `agy models`."
    ),
    task: Path | None = typer.Option(
        None, "--task", "-t", help="Path to a TaskContract YAML or JSON file."
    ),
    prompt_file: Path | None = typer.Option(
        None, "--prompt-file", help="Path to a text file containing the task prompt (legacy mode)."
    ),
) -> None:
    """Execute one task in a local Git repository via an AgentRunner and verify
    results with WorkspaceGuard and deterministic acceptance checks.
    """
    if provider != "antigravity":
        typer.echo(
            f"Error: unsupported provider '{provider}'. Only 'antigravity' is supported.",
            err=True,
        )
        raise typer.Exit(code=1)

    if task is None and prompt_file is None:
        typer.echo("Error: either --task or --prompt-file must be specified.", err=True)
        raise typer.Exit(code=1)

    try:
        repo_root = discover_repo_root(repo)
    except HandoffError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if task is not None:
        try:
            contract = load_task_contract(task)
        except TaskContractError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    else:
        assert prompt_file is not None
        if not prompt_file.exists():
            typer.echo(f"Error: prompt file not found: {prompt_file}", err=True)
            raise typer.Exit(code=1)
        raw_prompt = prompt_file.read_text(encoding="utf-8")
        contract = TaskContract(
            id="legacy-prompt-task",
            objective=raw_prompt,
            expected_changes=ExpectedChanges(required=False),
            allowed_paths=[],
            acceptance=[],
        )

    try:
        runner = select_runner(provider)
        result = run_verified_task(runner, contract, repo_root, config=AgentRunConfig(model=model))
    except (AgyNotFoundError, AgyVersionError, AgyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Run ID: {result.run_id}")
    typer.echo(
        f"Provider: {result.provider}  Model: {result.requested_model} "
        f"(resolved: {result.resolved_model or 'unknown'})"
    )
    typer.echo(f"Process exit status: {result.process_exit_status} (code: {result.exit_code})")
    if result.agent_report:
        typer.echo(f"Agent-reported status: {result.agent_report.status}")
    typer.echo(f"Workspace policy status: {result.workspace_policy_status}")
    if result.workspace_policy_violations:
        for v in result.workspace_policy_violations:
            typer.echo(f"  Violation: {v}", err=True)
    typer.echo(f"Acceptance status: {result.acceptance_status}")
    for acc in result.acceptance_results:
        status_str = "PASS" if acc.passed else f"FAIL (code {acc.exit_code})"
        typer.echo(f"  [{status_str}] {acc.command}")
    typer.echo(f"RepoOps Verdict: {result.verdict}")
    typer.echo(f"Changed files: {len(result.git_evidence.changed_files)}")
    typer.echo(f"Run record: {result.run_dir}")

    if result.verdict not in ("verified", "unverified"):
        raise typer.Exit(code=1)


@app.command(name="worklog-scan")
def worklog_scan(
    config: Path | None = CONFIG_OPTION,
    project: str | None = PROJECT_OPTION,
    tag: list[str] | None = TAG_OPTION,
) -> None:
    """Scan configured repositories (read-only) and record a worklog evidence snapshot."""
    try:
        cfg = load_config(config)
        cfg = filter_config(cfg, project=project, tags=tag)
    except (ConfigError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    snapshot = build_snapshot(cfg)
    conn = open_store(cfg.defaults.worklog_db)
    rows = record_snapshot(conn, cfg, snapshot)
    conn.close()
    typer.echo(f"Worklog snapshot recorded: {rows} repo row(s) -> {cfg.defaults.worklog_db}")


@app.command(name="worklog-weekly")
def worklog_weekly(
    week: str = typer.Option(..., "--week", help="ISO week, e.g. 2026-W28."),
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to repoops YAML config."),
) -> None:
    """Print worklog candidate rows for a week. These are evidence, not approved hours."""
    try:
        cfg = load_config(config)
    except (ConfigError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    start, end = iso_week_range(week)
    conn = open_store(cfg.defaults.worklog_db)
    candidates = compute_candidates(conn, start, end)
    conn.close()
    print_worklog_candidates(candidates)


@app.command(name="worklog-export")
def worklog_export(
    month: str = typer.Option(..., "--month", help="Month, e.g. 2026-06."),
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to repoops YAML config."),
    export_format: str = typer.Option("csv", "--format", help="Only 'csv' is supported."),
) -> None:
    """Export worklog candidate rows for a month as CSV. Not a final payroll report."""
    if export_format != "csv":
        raise typer.BadParameter("Only --format csv is supported.")

    try:
        cfg = load_config(config)
    except (ConfigError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    start, end = month_range(month)
    conn = open_store(cfg.defaults.worklog_db)
    candidates = compute_candidates(conn, start, end)
    conn.close()

    report_dir = ensure_dir(cfg.defaults.report_dir)
    out_path = report_dir / f"repoops-worklog-{month}.csv"
    write_candidates_csv(candidates, out_path)
    typer.echo(f"Worklog export: {out_path}")


@app.command(name="task-list")
def task_list(
    repo: Path = typer.Argument(Path("."), help="Path inside the local Git repository."),
) -> None:
    """List tasks in the repository backlog (.repoops/tasks/)."""
    try:
        repo_root = discover_repo_root(repo)
    except HandoffError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    backlog = load_backlog(repo_root)
    if not backlog:
        typer.echo("No tasks found in .repoops/tasks/")
        return

    typer.echo(f"Task Backlog ({len(backlog)} tasks) in {repo_root}:")
    typer.echo(f"{'ID':<15} {'STATUS':<10} {'PRI':<5} {'DEPS':<15} {'OBJECTIVE'}")
    typer.echo("-" * 75)
    for task in backlog:
        deps_str = ",".join(task.depends_on) if task.depends_on else "-"
        obj_snippet = task.objective.strip().replace("\n", " ")[:30]
        line = f"{task.id:<15} {task.status:<10} {task.priority:<5} {deps_str:<15} {obj_snippet}"
        typer.echo(line)


@app.command(name="task-next")
def task_next(
    repo: Path = typer.Argument(Path("."), help="Path inside the local Git repository."),
) -> None:
    """Show the next eligible task from the repository backlog."""
    try:
        repo_root = discover_repo_root(repo)
    except HandoffError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    backlog = load_backlog(repo_root)
    next_task = select_next_task(backlog, repo_root=repo_root)
    if next_task is None:
        typer.echo("No eligible tasks available in backlog.")
        return

    typer.echo(f"Next eligible task: {next_task.id} (priority: {next_task.priority})")
    typer.echo(f"Objective: {next_task.objective.strip()}")
    if next_task.depends_on:
        typer.echo(f"Dependencies: {', '.join(next_task.depends_on)}")


@app.command(name="task-status")
def task_status(
    repo: Path = typer.Argument(Path("."), help="Path inside the local Git repository."),
) -> None:
    """Show RepoOps integration branch status and backlog promotion details."""
    try:
        repo_root = discover_repo_root(repo)
    except HandoffError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    branch_name, int_head, origin_sha = ensure_integration_branch(repo_root)
    backlog = load_backlog(repo_root)

    typer.echo(f"Integration Branch: {branch_name}")
    typer.echo(f"Integration HEAD SHA: {int_head}")
    typer.echo(f"Origin Base SHA: {origin_sha}")
    typer.echo(f"Total Tasks in Backlog: {len(backlog)}")

    for task in backlog:
        base_sha_str = task.baseline_sha[:7] if task.baseline_sha else "None"
        prom_sha_str = task.promoted_commit_sha[:7] if task.promoted_commit_sha else "None"
        line = (
            f"  [{task.id}] status={task.status} promo={task.promotion_status} "
            f"base={base_sha_str} promoted={prom_sha_str} attempts={task.attempt_count}"
        )
        typer.echo(line)


@app.command(name="task-run-next")
def task_run_next(
    repo: Path = typer.Argument(Path("."), help="Path inside the local Git repository."),
    provider: str = typer.Option(
        "antigravity", "--provider", help="Agent provider to use. Only 'antigravity' is supported."
    ),
    model: str = typer.Option(
        ..., "--model", help="Model identifier, as returned by `agy models`."
    ),
) -> None:
    """Execute at most ONE eligible task in an isolated Git worktree."""
    if provider != "antigravity":
        typer.echo(
            f"Error: unsupported provider '{provider}'. Only 'antigravity' is supported.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        repo_root = discover_repo_root(repo)
    except HandoffError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        runner = select_runner(provider)
        outcome = run_next_task(repo_root, runner, config=AgentRunConfig(model=model))
    except TaskLockedError as exc:
        typer.echo(f"Lock error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except TaskBacklogError as exc:
        typer.echo(f"Task backlog error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (AgyNotFoundError, AgyVersionError, AgyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if outcome is None:
        typer.echo("No eligible tasks available to run.")
        return

    task, result, wt_path = outcome
    typer.echo(f"Executed Task: {task.id}")
    typer.echo(f"Baseline SHA: {task.baseline_sha or 'unknown'}")
    typer.echo(f"Worktree: {wt_path}")
    typer.echo(f"Run ID: {result.run_id}")
    typer.echo(f"RepoOps Verdict: {result.verdict}")
    typer.echo(f"Promotion Status: {task.promotion_status}")
    if task.promoted_commit_sha:
        typer.echo(f"Promoted Commit SHA: {task.promoted_commit_sha}")
    typer.echo(f"Task final status: {task.status}")
    typer.echo(f"Attempt Count: {task.attempt_count}")

    if result.verdict not in ("verified", "unverified"):
        raise typer.Exit(code=1)


@app.command(name="scheduler-run-once")
def scheduler_run_once_cmd(
    repo: Path = typer.Argument(Path("."), help="Path inside the local Git repository."),
    provider: str = typer.Option(
        "antigravity", "--provider", help="Agent provider to use. Only 'antigravity' is supported."
    ),
    model: str = typer.Option(
        ..., "--model", help="Model identifier, as returned by `agy models`."
    ),
    max_attempts: int = typer.Option(
        1, "--max-attempts", help="Maximum execution attempts per task."
    ),
) -> None:
    """Execute at most ONE eligible task unattended under repository scheduler lock."""
    if provider != "antigravity":
        typer.echo(
            f"Error: unsupported provider '{provider}'. Only 'antigravity' is supported.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        repo_root = discover_repo_root(repo)
    except HandoffError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        res = run_scheduler_once(
            repo_root,
            provider=provider,
            model=model,
            max_attempts=max_attempts,
        )
    except Exception as exc:
        typer.echo(f"Scheduler execution error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Scheduler Run ID: {res.scheduler_run_id}")
    typer.echo(f"Outcome: {res.outcome}")
    typer.echo(f"Reason: {res.reason}")
    if res.selected_task_id:
        typer.echo(f"Selected Task: {res.selected_task_id}")
    if res.agent_run_id:
        typer.echo(f"Agent Run ID: {res.agent_run_id}")
    if res.task_verdict:
        typer.echo(f"Task Verdict: {res.task_verdict}")
    if res.promoted_commit_sha:
        typer.echo(f"Promoted Commit SHA: {res.promoted_commit_sha}")
    if res.integration_head_before or res.integration_head_after:
        before_sha = res.integration_head_before or "none"
        after_sha = res.integration_head_after or "none"
        typer.echo(f"Integration HEAD: {before_sha} -> {after_sha}")

    if res.outcome in ("task_verified", "no_eligible_task"):
        raise typer.Exit(code=0)
    else:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
