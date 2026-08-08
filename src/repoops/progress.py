"""Minimal deterministic operator progress logging for RepoOps."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

ProgressCallback = Callable[[str, str], None]


def format_progress_line(stage: str, message: str, *, dt: datetime | None = None) -> str:
    """Format a single progress line with timestamp and fixed-width stage tag."""
    now = dt or datetime.now()
    timestamp = now.strftime("%H:%M:%S")
    return f"[{timestamp}] {stage:<10} {message}"


def log_progress(stage: str, message: str) -> None:
    """Default progress reporter: write formatted line to stdout immediately."""
    print(format_progress_line(stage, message), flush=True)
