from pathlib import Path

import pytest

from repoops import notify, telegram
from repoops.config import RepoOpsConfig
from repoops.notify import notify_report

_TELEGRAM_ENABLED_CONFIG = {
    "machine": {"name": "nasapcdeb"},
    "notifications": {"enabled": True, "channel": "telegram"},
    "repos": [],
}


def _set_telegram_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(notify.TELEGRAM_BOT_TOKEN_ENV, "SECRET_TOKEN_VALUE")
    monkeypatch.setenv(notify.TELEGRAM_CHAT_ID_ENV, "123456")


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


def test_notify_does_not_log_secret_env_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_notify_telegram_sends_synthesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "report.md"
    report.write_text(
        "# repoops report\n\n"
        "## Summary\n\n- Dirty repos: `1`\n\n"
        "## Repositories\n\n### dihiggs\n\n- Path: `/home/fabian/dihiggs`\n",
        encoding="utf-8",
    )
    _set_telegram_env(monkeypatch)
    captured: dict[str, str] = {}

    def fake_send_message(
        *, bot_token: str, chat_id: str, text: str, timeout: float = 10.0
    ) -> None:
        captured["bot_token"] = bot_token
        captured["chat_id"] = chat_id
        captured["text"] = text

    monkeypatch.setattr(telegram, "send_message", fake_send_message)
    cfg = RepoOpsConfig.model_validate(_TELEGRAM_ENABLED_CONFIG)

    result = notify_report(cfg, report)

    assert result.status == "sent"
    assert result.channel == "telegram"
    assert captured["bot_token"] == "SECRET_TOKEN_VALUE"
    assert captured["chat_id"] == "123456"
    assert "## Summary" in captured["text"]
    assert "### dihiggs" not in captured["text"]


def test_notify_telegram_missing_env_vars_raises(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("# repoops report\n", encoding="utf-8")
    cfg = RepoOpsConfig.model_validate(_TELEGRAM_ENABLED_CONFIG)

    with pytest.raises(ValueError, match="REPOOPS_TELEGRAM_BOT_TOKEN"):
        notify_report(cfg, report)


def test_notify_telegram_send_failure_is_non_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "report.md"
    report.write_text("# repoops report\n", encoding="utf-8")
    _set_telegram_env(monkeypatch)

    def fake_send_message(**_kwargs: object) -> None:
        raise telegram.TelegramError("Telegram API returned HTTP 401")

    monkeypatch.setattr(telegram, "send_message", fake_send_message)
    cfg = RepoOpsConfig.model_validate(_TELEGRAM_ENABLED_CONFIG)

    result = notify_report(cfg, report)

    assert result.status == "skipped"
    assert result.channel == "telegram"
    assert "401" in (result.reason or "")


def test_synthesize_telegram_text_keeps_summary_drops_repo_detail() -> None:
    report_text = (
        "# repoops report\n\n## Summary\n\n- Dirty repos: `1`\n\n"
        "## Repositories\n\n### dihiggs\n\n- Path: `/home/fabian/dihiggs`\n"
    )

    text = notify._synthesize_telegram_text(report_text)

    assert "## Summary" in text
    assert "## Repositories" not in text
    assert "dihiggs" not in text


def test_synthesize_telegram_text_truncates_long_header() -> None:
    header = "# repoops report\n\n" + ("x" * 5000)

    text = notify._synthesize_telegram_text(header, limit=100)

    assert len(text) <= 100
    assert text.endswith("[truncated — see full report file]")
