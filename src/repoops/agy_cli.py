"""Detection and invocation helpers for the Antigravity CLI (`agy`).

This module never talks to the network and never spawns a long-running
process itself -- it only detects the `agy` binary, checks its version, and
discovers available models via `agy models`. The actual streaming task
invocation lives in `repoops.agent_runner`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

MIN_AGY_VERSION: tuple[int, int, int] = (1, 1, 10)

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_MODEL_HEADER_TOKENS = {"NAME", "MODEL", "MODELS", "ID"}


class AgyError(RuntimeError):
    """Base exception for problems detecting or invoking the Antigravity CLI."""


class AgyNotFoundError(AgyError):
    """Raised when the `agy` executable cannot be found on PATH."""


class AgyVersionError(AgyError):
    """Raised when `agy --version` cannot be parsed or is below `MIN_AGY_VERSION`."""


def find_agy() -> str:
    """Locate the `agy` executable on PATH. Read-only; does not execute it."""
    resolved = shutil.which("agy")
    if resolved is None:
        raise AgyNotFoundError(
            "Antigravity CLI ('agy') was not found on PATH. Install it and ensure "
            "it is reachable before running `repoops agent-run`."
        )
    return resolved


def parse_agy_version(raw: str) -> tuple[int, int, int]:
    """Extract a `(major, minor, patch)` tuple from `agy --version` output."""
    match = _VERSION_RE.search(raw)
    if not match:
        raise AgyVersionError(f"Could not parse Antigravity CLI version from output: {raw!r}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def detect_agy_version(agy_path: str) -> tuple[str, tuple[int, int, int]]:
    """Run `agy --version` and return `(raw_output, parsed_version)`."""
    proc = subprocess.run([agy_path, "--version"], capture_output=True, text=True, check=False)
    raw = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if proc.returncode != 0 and not raw:
        raise AgyVersionError(f"Failed to run '{agy_path} --version' (exit {proc.returncode}).")
    return raw, parse_agy_version(raw)


def require_agy(min_version: tuple[int, int, int] = MIN_AGY_VERSION) -> str:
    """Find `agy`, verify its version meets `min_version`, and return its path.

    Raises `AgyNotFoundError` if missing and `AgyVersionError` if the detected
    version is older than required or unparseable.
    """
    agy_path = find_agy()
    raw, version = detect_agy_version(agy_path)
    if version < min_version:
        raise AgyVersionError(
            f"Antigravity CLI version {'.'.join(map(str, version))} is older than "
            f"the required minimum {'.'.join(map(str, min_version))}. "
            f"Detected output: {raw!r}"
        )
    return agy_path


def parse_models_output(raw: str) -> list[str]:
    """Parse `agy models` stdout into a list of model identifiers.

    Heuristic: each non-empty line's first whitespace-separated token is a
    model id, skipping separator lines (`---`) and an optional header row
    (`NAME`, `MODEL`, `MODELS`, `ID`). This intentionally does not hard-code
    any specific model names -- the catalogue is provider-controlled.
    """
    models: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if set(stripped) <= {"-", "=", " "}:
            continue
        first_token = stripped.split()[0]
        if first_token.upper() in _MODEL_HEADER_TOKENS:
            continue
        if first_token not in models:
            models.append(first_token)
    return models


def discover_models(agy_path: str) -> list[str]:
    """Run `agy models` and return the discovered model identifiers."""
    proc = subprocess.run([agy_path, "models"], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AgyError(
            f"Failed to run '{agy_path} models' (exit {proc.returncode}): "
            f"{(proc.stderr or '').strip()}"
        )
    return parse_models_output(proc.stdout)


def build_agy_argv(
    agy_path: str,
    *,
    model: str,
    schema_path: Path,
    prompt: str,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Build the headless `agy` invocation argv.

    Equivalent to:
    `agy --model <MODEL> --output-format stream-json --json-schema <SCHEMA> -p <PROMPT>`

    Never includes `--dangerously-skip-permissions` or any other permission-widening
    flag; only what the caller explicitly passes via `extra_args` is added.
    """
    argv = [
        agy_path,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--json-schema",
        str(schema_path),
        "-p",
        prompt,
    ]
    if extra_args:
        argv.extend(extra_args)
    return argv
