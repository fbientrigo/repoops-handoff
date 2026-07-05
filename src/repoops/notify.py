"""Notification boundary for repoops reports."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from repoops import telegram
from repoops.config import NotificationChannel, RepoOpsConfig
from repoops.paths import expand_path

TELEGRAM_BOT_TOKEN_ENV = "REPOOPS_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV = "REPOOPS_TELEGRAM_CHAT_ID"
TELEGRAM_MESSAGE_LIMIT = 4096
_TELEGRAM_TRUNCATION_SUFFIX = "\n\n[truncated — see full report file]"
_REPORT_DETAIL_HEADING = "## Repositories"


class NotifyResult(BaseModel):
    status: Literal["sent", "skipped"]
    channel: str
    reason: str | None = None


def _synthesize_telegram_text(report_text: str, *, limit: int = TELEGRAM_MESSAGE_LIMIT) -> str:
    """Condense a rendered Markdown report into a short push-notification body.

    Keeps only the header/Summary/Attention summary sections — everything
    before the per-repo `## Repositories` detail section — so a phone
    notification stays a small synthesis even when the full report covers
    many repositories.
    """
    header, _, _ = report_text.partition(_REPORT_DETAIL_HEADING)
    text = header.rstrip()
    if len(text) <= limit:
        return text
    return text[: limit - len(_TELEGRAM_TRUNCATION_SUFFIX)].rstrip() + _TELEGRAM_TRUNCATION_SUFFIX


def _send_telegram(report_text: str) -> NotifyResult:
    bot_token = os.environ.get(TELEGRAM_BOT_TOKEN_ENV)
    chat_id = os.environ.get(TELEGRAM_CHAT_ID_ENV)
    missing = [
        name
        for name, value in ((TELEGRAM_BOT_TOKEN_ENV, bot_token), (TELEGRAM_CHAT_ID_ENV, chat_id))
        if not value
    ]
    if missing:
        raise ValueError(
            "Telegram notification requires environment variables: " + ", ".join(missing)
        )

    text = _synthesize_telegram_text(report_text)
    try:
        telegram.send_message(bot_token=bot_token, chat_id=chat_id, text=text)
    except telegram.TelegramError as exc:
        return NotifyResult(status="skipped", channel="telegram", reason=str(exc))

    return NotifyResult(status="sent", channel="telegram")


def notify_report(config: RepoOpsConfig, report_path: str | Path) -> NotifyResult:
    """Send or skip a report according to notification config.

    Disabled and `none` are safe no-op paths. Telegram sends a short synthesis
    derived from the rendered Markdown report. Slack and SMTP remain explicit
    stubs.
    """
    expanded_report_path = expand_path(report_path)
    if not expanded_report_path.exists():
        raise FileNotFoundError(f"Report file not found: {expanded_report_path}")

    notifications = config.notifications
    if not notifications.enabled:
        return NotifyResult(
            status="skipped",
            channel=notifications.channel.value,
            reason="notifications disabled",
        )

    if notifications.channel == NotificationChannel.NONE:
        return NotifyResult(status="skipped", channel="none", reason="channel none")

    if notifications.channel == NotificationChannel.TELEGRAM:
        report_text = expanded_report_path.read_text(encoding="utf-8")
        return _send_telegram(report_text)

    # Do not read or print secret environment values here.
    # Backend implementations should resolve env var names internally and never expose values.
    raise NotImplementedError(
        f"Notification channel '{notifications.channel.value}' is not implemented "
        "in the v0 skeleton."
    )
