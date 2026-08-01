"""Path helpers for repoops."""

import contextlib
import os
import tempfile
from pathlib import Path


def expand_path(path: str | Path) -> Path:
    """Expand user markers and return an absolute path without requiring existence."""
    return Path(path).expanduser().resolve(strict=False)


def ensure_dir(path: str | Path) -> Path:
    """Create a directory if needed and return its expanded absolute path."""
    expanded = expand_path(path)
    expanded.mkdir(parents=True, exist_ok=True)
    return expanded


def atomic_write_text(path: str | Path, content: str, *, encoding: str = "utf-8") -> Path:
    """Write `content` to `path` atomically via a same-directory temp file + rename."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
        os.replace(tmp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_name)
        raise
    return target
