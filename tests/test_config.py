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
            group: physics
        """,
    )

    cfg = load_config(config_path)

    assert cfg.machine.name == "nasapcdeb"
    assert cfg.notifications.enabled is False
    assert cfg.notifications.channel == NotificationChannel.NONE
    assert cfg.repos[0].name == "dihiggs"
    assert cfg.repos[0].group == "physics"


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
