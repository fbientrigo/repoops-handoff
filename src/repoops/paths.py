"""Path helpers for repoops."""

from pathlib import Path


def expand_path(path: str | Path) -> Path:
    """Expand user markers and return an absolute path without requiring existence."""
    return Path(path).expanduser().resolve(strict=False)


def ensure_dir(path: str | Path) -> Path:
    """Create a directory if needed and return its expanded absolute path."""
    expanded = expand_path(path)
    expanded.mkdir(parents=True, exist_ok=True)
    return expanded
