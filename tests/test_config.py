from pathlib import Path

import pytest

from repoops.config import NotificationChannel, load_config


def write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_load_minimal_config(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "repos.yaml",
        """
        machine:
          name: nasapcdeb
        notifications:
          enabled: false
          channel: none
        repos:
          - name: dihiggs
            path: ~/dihiggs
        """,
    )

    cfg = load_config(config_path)

    assert cfg.machine.name == "nasapcdeb"
    assert cfg.notifications.enabled is False
    assert cfg.notifications.channel == NotificationChannel.NONE
    assert cfg.repos[0].name == "dihiggs"


def test_config_expands_user_paths(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "repos.yaml",
        """
        machine:
          name: nasapcdeb
        repos:
          - name: dihiggs
            path: ~/dihiggs
        """,
    )

    cfg = load_config(config_path)

    assert "~" not in str(cfg.repos[0].path)
    assert cfg.repos[0].path.is_absolute()


def test_config_rejects_missing_repo_name(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "repos.yaml",
        """
        machine:
          name: nasapcdeb
        repos:
          - path: ~/dihiggs
        """,
    )

    with pytest.raises(ValueError):
        load_config(config_path)


def test_config_accepts_notification_none(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "repos.yaml",
        """
        machine:
          name: nasapcdeb
        notifications:
          enabled: true
          channel: none
        repos: []
        """,
    )

    cfg = load_config(config_path)

    assert cfg.notifications.enabled is True
    assert cfg.notifications.channel == NotificationChannel.NONE


def test_defaults_remote_check_fetch_settings(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "repos.yaml",
        """
        machine:
          name: nasapcdeb
        repos: []
        """,
    )

    cfg = load_config(config_path)

    assert cfg.defaults.remote_check is True
    assert cfg.defaults.fetch is False
    assert cfg.defaults.fetch_timeout_seconds == 20


def test_worklog_db_defaults_and_repo_project_is_optional(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "repos.yaml",
        """
        machine:
          name: nasapcdeb
        repos:
          - name: dihiggs
            path: ~/dihiggs
        """,
    )

    cfg = load_config(config_path)

    assert cfg.defaults.worklog_db.name == "worklog.db"
    assert cfg.repos[0].project is None


def test_config_overrides_worklog_db_and_repo_project(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "repos.yaml",
        """
        machine:
          name: nasapcdeb
        defaults:
          worklog_db: ~/custom/worklog.db
        repos:
          - name: apolo-rag
            path: ~/apolo_rag
            project: Apolo
        """,
    )

    cfg = load_config(config_path)

    assert cfg.defaults.worklog_db.name == "worklog.db"
    assert "custom" in str(cfg.defaults.worklog_db)
    assert cfg.repos[0].project == "Apolo"


def test_config_overrides_remote_and_fetch_settings(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "repos.yaml",
        """
        machine:
          name: nasapcdeb
        defaults:
          remote_check: false
          fetch: true
          fetch_timeout_seconds: 5
        repos: []
        """,
    )

    cfg = load_config(config_path)

    assert cfg.defaults.remote_check is False
    assert cfg.defaults.fetch is True
    assert cfg.defaults.fetch_timeout_seconds == 5
