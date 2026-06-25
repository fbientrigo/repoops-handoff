from pathlib import Path

import pytest

from repoops.config import RepoOpsConfig
from repoops.notify import notify_report


def test_notify_disabled_is_noop(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("# report\n", encoding="utf-8")
    cfg = RepoOpsConfig.model_validate(
        {
            "machine": {"name": "nasapcdeb"},
            "notifications": {"enabled": False, "channel": "telegram"},
            "repos": [],
        }
    )

    result = notify_report(cfg, report)

    assert result.status == "skipped"
    assert result.reason == "notifications disabled"


def test_notify_channel_none_is_noop(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("# report\n", encoding="utf-8")
    cfg = RepoOpsConfig.model_validate(
        {
            "machine": {"name": "nasapcdeb"},
            "notifications": {"enabled": True, "channel": "none"},
            "repos": [],
        }
    )

    result = notify_report(cfg, report)

    assert result.status == "skipped"
    assert result.reason == "channel none"


def test_notify_missing_report_fails_cleanly(tmp_path: Path) -> None:
    cfg = RepoOpsConfig.model_validate(
        {
            "machine": {"name": "nasapcdeb"},
            "notifications": {"enabled": False, "channel": "none"},
            "repos": [],
        }
    )

    with pytest.raises(FileNotFoundError):
        notify_report(cfg, tmp_path / "missing.md")


def test_notify_does_not_log_secret_env_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = tmp_path / "report.md"
    report.write_text("# report\n", encoding="utf-8")
    monkeypatch.setenv("REPOOPS_TELEGRAM_BOT_TOKEN", "SECRET_TOKEN_VALUE")
    cfg = RepoOpsConfig.model_validate(
        {
            "machine": {"name": "nasapcdeb"},
            "notifications": {"enabled": False, "channel": "telegram"},
            "repos": [],
        }
    )

    result = notify_report(cfg, report)

    assert "SECRET_TOKEN_VALUE" not in result.model_dump_json()
    assert "REPOOPS_TELEGRAM_BOT_TOKEN" not in result.model_dump_json()
