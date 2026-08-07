from __future__ import annotations

import pytest

from repoops.agy_cli import (
    AgyNotFoundError,
    AgyVersionError,
    build_agy_argv,
    find_agy,
    parse_agy_version,
    parse_models_output,
    require_agy,
)

# --- missing agy --------------------------------------------------------------


def test_find_agy_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("repoops.agy_cli.shutil.which", lambda name: None)
    with pytest.raises(AgyNotFoundError):
        find_agy()


def test_require_agy_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("repoops.agy_cli.shutil.which", lambda name: None)
    with pytest.raises(AgyNotFoundError):
        require_agy()


# --- version parsing / gating --------------------------------------------------


def test_parse_agy_version_extracts_semver() -> None:
    assert parse_agy_version("agy version 1.2.3") == (1, 2, 3)


def test_parse_agy_version_raises_on_unparseable_output() -> None:
    with pytest.raises(AgyVersionError):
        parse_agy_version("no version info here")


def test_require_agy_raises_on_unsupported_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("repoops.agy_cli.shutil.which", lambda name: "/usr/bin/agy")

    class FakeProc:
        returncode = 0
        stdout = "agy version 1.0.0\n"
        stderr = ""

    monkeypatch.setattr("repoops.agy_cli.subprocess.run", lambda *a, **k: FakeProc())
    with pytest.raises(AgyVersionError):
        require_agy()


def test_require_agy_accepts_supported_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("repoops.agy_cli.shutil.which", lambda name: "/usr/bin/agy")

    class FakeProc:
        returncode = 0
        stdout = "agy version 1.1.10\n"
        stderr = ""

    monkeypatch.setattr("repoops.agy_cli.subprocess.run", lambda *a, **k: FakeProc())
    assert require_agy() == "/usr/bin/agy"


# --- model discovery parsing ----------------------------------------------------


def test_parse_models_output_skips_header_and_separators() -> None:
    raw = (
        "NAME              DESCRIPTION\n"
        "----              -----------\n"
        "gemini-2.5-pro    Balanced flagship model\n"
        "gemini-2.5-flash  Fast, low-latency model\n"
    )
    assert parse_models_output(raw) == ["gemini-2.5-pro", "gemini-2.5-flash"]


def test_parse_models_output_deduplicates_and_ignores_blank_lines() -> None:
    raw = "\nmodel-a\n\nmodel-a\nmodel-b\n"
    assert parse_models_output(raw) == ["model-a", "model-b"]


# --- argv construction -----------------------------------------------------------


def test_build_agy_argv_matches_headless_contract(tmp_path) -> None:
    schema_path = tmp_path / "schema.json"
    argv = build_agy_argv(
        "/usr/bin/agy", model="gemini-2.5-pro", schema_path=schema_path, prompt="do the task"
    )
    assert argv == [
        "/usr/bin/agy",
        "--model",
        "gemini-2.5-pro",
        "--output-format",
        "stream-json",
        "--json-schema",
        str(schema_path),
        "-p",
        "do the task",
    ]
    assert "--dangerously-skip-permissions" not in argv
