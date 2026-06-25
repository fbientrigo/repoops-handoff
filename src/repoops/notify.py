"""Notification boundary for repoops reports."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from repoops.config import NotificationChannel, RepoOpsConfig
from repoops.paths import expand_path


class NotifyResult(BaseModel):
    status: Literal["sent", "skipped"]
    channel: str
    reason: str | None = None


def notify_report(config: RepoOpsConfig, report_path: str | Path) -> NotifyResult:
    """Send or skip a report according to notification config.

    v0 skeleton implements disabled and `none` as safe no-op paths.
    External Telegram, Slack, and SMTP channels are intentionally left as explicit stubs.
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

    # Do not read or print secret environment values here.
    # Backend implementations should resolve env var names internally and never expose values.
    raise NotImplementedError(
        f"Notification channel '{notifications.channel.value}' is not implemented in the v0 skeleton."
    )
