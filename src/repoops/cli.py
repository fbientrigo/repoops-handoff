"""Typer CLI for repoops."""

from pathlib import Path

import typer

from repoops.config import load_config
from repoops.git_scan import build_snapshot
from repoops.handoff import HandoffError, create_checkpoint, handoff_paths, run_resume
from repoops.handoff_render import render_resume_report
from repoops.notify import notify_report
from repoops.paths import ensure_dir
from repoops.report import print_summary_table, print_worklog_candidates, render_markdown
from repoops.worklog import (
    compute_candidates,
    iso_week_range,
    month_range,
    open_store,
    record_snapshot,
    write_candidates_csv,
)

app = typer.Typer(help="Low-noise multi-repository status reporter.")


FETCH_OPTION_HELP = (
    "Force a safe `git fetch --prune` before computing ahead/behind status. "
    "Updates remote-tracking refs only — never the working tree, never pulls or pushes."
)


@app.command()
def scan(
    config: Path = typer.Option(..., "--config", "-c", help="Path to repoops YAML config."),
    fetch: bool = typer.Option(False, "--fetch", help=FETCH_OPTION_HELP),
) -> None:
    """Scan configured repositories and print a terminal table."""
    cfg = load_config(config)
    snapshot = build_snapshot(cfg, cli_fetch=fetch)
    print_summary_table(snapshot)


@app.command()
def run(
    config: Path = typer.Option(..., "--config", "-c", help="Path to repoops YAML config."),
    fetch: bool = typer.Option(False, "--fetch", help=FETCH_OPTION_HELP),
) -> None:
    """Scan configured repositories and write JSON + Markdown artifacts."""
    cfg = load_config(config)
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
    config: Path = typer.Option(..., "--config", "-c", help="Path to repoops YAML config."),
    report: Path = typer.Option(..., "--report", "-r", help="Path to an existing Markdown report."),
) -> None:
    """Send or no-op an existing report according to config."""
    cfg = load_config(config)
    result = notify_report(cfg, report)
    typer.echo(f"Notification: {result.status} ({result.reason or result.channel})")


@app.command()
def checkpoint(
    path: Path = typer.Argument(
        Path("."), help="Path inside the Git repository to checkpoint. Defaults to '.'."
    ),
) -> None:
    """Write a deterministic handoff checkpoint (.repoops/handoff.json + HANDOFF.md)."""
    try:
        handoff = create_checkpoint(path)
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


@app.command(name="worklog-scan")
def worklog_scan(
    config: Path = typer.Option(..., "--config", "-c", help="Path to repoops YAML config."),
) -> None:
    """Scan configured repositories (read-only) and record a worklog evidence snapshot."""
    cfg = load_config(config)
    snapshot = build_snapshot(cfg)
    conn = open_store(cfg.defaults.worklog_db)
    rows = record_snapshot(conn, cfg, snapshot)
    conn.close()
    typer.echo(f"Worklog snapshot recorded: {rows} repo row(s) -> {cfg.defaults.worklog_db}")


@app.command(name="worklog-weekly")
def worklog_weekly(
    config: Path = typer.Option(..., "--config", "-c", help="Path to repoops YAML config."),
    week: str = typer.Option(..., "--week", help="ISO week, e.g. 2026-W28."),
) -> None:
    """Print worklog candidate rows for a week. These are evidence, not approved hours."""
    cfg = load_config(config)
    start, end = iso_week_range(week)
    conn = open_store(cfg.defaults.worklog_db)
    candidates = compute_candidates(conn, start, end)
    conn.close()
    print_worklog_candidates(candidates)


@app.command(name="worklog-export")
def worklog_export(
    config: Path = typer.Option(..., "--config", "-c", help="Path to repoops YAML config."),
    month: str = typer.Option(..., "--month", help="Month, e.g. 2026-06."),
    export_format: str = typer.Option("csv", "--format", help="Only 'csv' is supported."),
) -> None:
    """Export worklog candidate rows for a month as CSV. Not a final payroll report."""
    if export_format != "csv":
        raise typer.BadParameter("Only --format csv is supported.")

    cfg = load_config(config)
    start, end = month_range(month)
    conn = open_store(cfg.defaults.worklog_db)
    candidates = compute_candidates(conn, start, end)
    conn.close()

    report_dir = ensure_dir(cfg.defaults.report_dir)
    out_path = report_dir / f"repoops-worklog-{month}.csv"
    write_candidates_csv(candidates, out_path)
    typer.echo(f"Worklog export: {out_path}")


if __name__ == "__main__":
    app()
