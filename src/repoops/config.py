"""Configuration loading and validation."""

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from repoops.paths import expand_path

DEFAULT_CONFIG_PATH = expand_path("~/.config/repoops/repos.yaml")


class ConfigError(Exception):
    """Base exception for config resolution and validation errors."""

    pass


class ConfigNotFoundError(ConfigError, FileNotFoundError):
    """Raised when no configuration file can be resolved or found."""

    pass


class FilterNoMatchError(ConfigError, ValueError):
    """Raised when filtering options match zero configured repositories."""

    pass


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
    worklog_db: Path = Path("~/.local/share/repoops/worklog.db")
    many_changes_threshold: int = Field(default=20, ge=1)
    remote_check: bool = True
    fetch: bool = False
    fetch_timeout_seconds: int = Field(default=20, ge=1)

    @field_validator("report_dir", "snapshot_dir", "worklog_db", mode="before")
    @classmethod
    def _expand_output_path(cls, value: str | Path) -> Path:
        return expand_path(value)


class NotificationConfig(BaseModel):
    enabled: bool = False
    channel: NotificationChannel = NotificationChannel.NONE


class RepoConfig(BaseModel):
    name: str = Field(min_length=1)
    path: Path
    project: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("path", mode="before")
    @classmethod
    def _expand_repo_path(cls, value: str | Path) -> Path:
        return expand_path(value)

    @field_validator("project", mode="before")
    @classmethod
    def _validate_project(cls, value: Any) -> str | None:
        if value is None:
            return None
        stripped = str(value).strip()
        if not stripped:
            return None
        return stripped

    @field_validator("tags", mode="before")
    @classmethod
    def _validate_tags(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("tags must be a list of strings")
        cleaned_tags: list[str] = []
        seen_lower: set[str] = set()
        for item in value:
            item_str = str(item) if item is not None else ""
            stripped = item_str.strip()
            if not stripped:
                raise ValueError("Tag cannot be empty.")
            lower = stripped.lower()
            if lower not in seen_lower:
                seen_lower.add(lower)
                cleaned_tags.append(stripped)
        return cleaned_tags


class RepoOpsConfig(BaseModel):
    machine: MachineConfig
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    repos: list[RepoConfig] = Field(default_factory=list)


def resolve_config_path(path: str | Path | None = None) -> Path:
    """Resolve configuration file path based on precedence rules.

    Precedence:
    1. Explicit path parameter (if provided)
    2. Environment variable REPOOPS_CONFIG
    3. Default path (~/.config/repoops/repos.yaml)
    """
    if path is not None:
        return expand_path(path)

    env_config = os.environ.get("REPOOPS_CONFIG")
    if env_config and env_config.strip():
        return expand_path(env_config.strip())

    return DEFAULT_CONFIG_PATH


def load_config(path: str | Path | None = None) -> RepoOpsConfig:
    """Load and validate a repoops YAML config."""
    config_path = resolve_config_path(path)
    if not config_path.exists():
        raise ConfigNotFoundError(
            f"Config file not found: {config_path}\n"
            f"Default location checked: {DEFAULT_CONFIG_PATH}\n"
            "Specify a configuration file using --config/-c or set REPOOPS_CONFIG "
            "environment variable."
        )

    with config_path.open("r", encoding="utf-8") as handle:
        raw: Any = yaml.safe_load(handle) or {}

    try:
        return RepoOpsConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid repoops config: {exc}") from exc


def filter_config(
    config: RepoOpsConfig,
    project: str | None = None,
    tags: list[str] | None = None,
) -> RepoOpsConfig:
    """Filter repositories in config by project and/or tags.

    Matches case-insensitively after stripping whitespace.
    If no filters are provided, returns the original config.
    If filters are provided but match no repositories, raises FilterNoMatchError.
    Preserves configured repository order.
    """
    cleaned_project = project.strip() if project and project.strip() else None
    cleaned_tags = [t.strip() for t in (tags or []) if t and t.strip()]

    if tags is not None:
        for orig_tag in tags:
            if not orig_tag or not orig_tag.strip():
                raise ValueError("Tag filter cannot be empty.")

    if not cleaned_project and not cleaned_tags:
        return config

    matching_repos: list[RepoConfig] = []
    target_project_lower = cleaned_project.lower() if cleaned_project else None
    target_tags_lower = [t.lower() for t in cleaned_tags]

    for repo in config.repos:
        # Check project match
        if target_project_lower is not None and (
            not repo.project or repo.project.strip().lower() != target_project_lower
        ):
            continue

        # Check tags match (repo must contain ALL requested tags)
        if target_tags_lower:
            repo_tags_lower = {t.lower() for t in repo.tags}
            if not all(req_tag in repo_tags_lower for req_tag in target_tags_lower):
                continue

        matching_repos.append(repo)

    if not matching_repos:
        known_projects = sorted(
            {r.project.strip() for r in config.repos if r.project and r.project.strip()}
        )
        known_tags = sorted({t for r in config.repos for t in r.tags if t and t.strip()})

        filter_desc_parts = []
        if cleaned_project:
            filter_desc_parts.append(f"project='{cleaned_project}'")
        if cleaned_tags:
            filter_desc_parts.append(f"tags={cleaned_tags}")
        filter_desc = ", ".join(filter_desc_parts)

        projects_str = ", ".join(known_projects) if known_projects else "(none)"
        tags_str = ", ".join(known_tags) if known_tags else "(none)"

        raise FilterNoMatchError(
            f"No repositories matched requested filters ({filter_desc}).\n"
            f"Known projects: {projects_str}\n"
            f"Known tags: {tags_str}"
        )

    return config.model_copy(update={"repos": matching_repos})
