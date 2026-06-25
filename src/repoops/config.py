"""Configuration loading and validation."""

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from repoops.paths import expand_path


class NotificationChannel(StrEnum):
    """Supported v0 notification channels."""

    TELEGRAM = "telegram"
    SLACK = "slack"
    EMAIL = "email"
    NONE = "none"


class MachineConfig(BaseModel):
    name: str = Field(min_length=1)


class DefaultsConfig(BaseModel):
    max_files_per_repo: int = Field(default=12, ge=0)
    include_untracked: bool = True
    include_clean_repos: bool = False
    report_dir: Path = Path("~/.local/share/repoops/reports")
    snapshot_dir: Path = Path("~/.local/share/repoops/snapshots")
    many_changes_threshold: int = Field(default=20, ge=1)

    @field_validator("report_dir", "snapshot_dir", mode="before")
    @classmethod
    def _expand_output_path(cls, value: str | Path) -> Path:
        return expand_path(value)


class TelegramConfig(BaseModel):
    bot_token_env: str = "REPOOPS_TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "REPOOPS_TELEGRAM_CHAT_ID"


class SlackConfig(BaseModel):
    webhook_url_env: str = "REPOOPS_SLACK_WEBHOOK_URL"


class EmailConfig(BaseModel):
    smtp_host_env: str = "REPOOPS_SMTP_HOST"
    smtp_port_env: str = "REPOOPS_SMTP_PORT"
    username_env: str = "REPOOPS_SMTP_USERNAME"
    password_env: str = "REPOOPS_SMTP_PASSWORD"
    from_env: str = "REPOOPS_EMAIL_FROM"
    to_env: str = "REPOOPS_EMAIL_TO"


class NotificationConfig(BaseModel):
    enabled: bool = False
    channel: NotificationChannel = NotificationChannel.NONE
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)


class RepoConfig(BaseModel):
    name: str = Field(min_length=1)
    path: Path
    group: str | None = None

    @field_validator("path", mode="before")
    @classmethod
    def _expand_repo_path(cls, value: str | Path) -> Path:
        return expand_path(value)


class RepoOpsConfig(BaseModel):
    machine: MachineConfig
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    repos: list[RepoConfig] = Field(default_factory=list)


def load_config(path: str | Path) -> RepoOpsConfig:
    """Load and validate a repoops YAML config."""
    config_path = expand_path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw: Any = yaml.safe_load(handle) or {}

    try:
        return RepoOpsConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid repoops config: {exc}") from exc
