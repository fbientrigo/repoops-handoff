"""Typer CLI for repoops."""

from pathlib import Path

import typer

from repoops.config import load_config
from repoops.git_scan import build_snapshot
from repoops.notify import notify_report
from repoops.paths import ensure_dir
from repoops.report import print_summary_table, render_markdown

app = typer.Typer(help="Low-noise multi-repository status reporter.")


@app.command()
def scan(
    config: Path = typer.Option(..., "--config", "-c", help="Path to repoops YAML config."),
) -> None:
    """Scan configured repositories and print a terminal table."""
    cfg = load_config(config)
    snapshot = build_snapshot(cfg)
    print_summary_table(snapshot)


@app.command()
def run(
    config: Path = typer.Option(..., "--config", "-c", help="Path to repoops YAML config."),
) -> None:
    """Scan configured repositories and write JSON + Markdown artifacts."""
    cfg = load_config(config)
    snapshot = build_snapshot(cfg)
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


if __name__ == "__main__":
    app()
