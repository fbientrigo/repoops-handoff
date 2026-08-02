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


def test_repo_config_tags_validation_and_deduplication(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "repos.yaml",
        """
        machine:
          name: dev
        repos:
          - name: ship-repo
            path: ~/ship
            project: thesis
            tags:
              - thesis
              -  ship 
              - THESIS
              - ml
        """,
    )

    cfg = load_config(config_path)
    assert cfg.repos[0].tags == ["thesis", "ship", "ml"]


def test_repo_config_rejects_empty_tags(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "repos.yaml",
        """
        machine:
          name: dev
        repos:
          - name: ship-repo
            path: ~/ship
            tags:
              - "   "
        """,
    )

    with pytest.raises(ValueError, match="Tag cannot be empty"):
        load_config(config_path)


def test_resolve_config_path_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from repoops.config import DEFAULT_CONFIG_PATH, resolve_config_path

    # 1. Explicit path parameter has highest precedence
    explicit = tmp_path / "explicit.yaml"
    monkeypatch.setenv("REPOOPS_CONFIG", str(tmp_path / "env.yaml"))
    assert resolve_config_path(explicit) == explicit.resolve(strict=False)

    # 2. REPOOPS_CONFIG env var has second precedence
    assert resolve_config_path(None) == (tmp_path / "env.yaml").resolve(strict=False)

    # 3. Default path when neither explicit nor env var is provided
    monkeypatch.delenv("REPOOPS_CONFIG", raising=False)
    assert resolve_config_path(None) == DEFAULT_CONFIG_PATH


def test_filter_config_project_and_tags(tmp_path: Path) -> None:
    from repoops.config import FilterNoMatchError, filter_config

    config_path = write_config(
        tmp_path / "repos.yaml",
        """
        machine:
          name: dev
        repos:
          - name: r1
            path: ~/r1
            project: thesis
            tags: [thesis, ship, ml]
          - name: r2
            path: ~/r2
            project: thesis
            tags: [thesis, sampling]
          - name: r3
            path: ~/r3
            project: apolo
            tags: [apolo, rag]
        """,
    )

    cfg = load_config(config_path)

    # Filter by project (case insensitive)
    f_proj = filter_config(cfg, project="THESIS")
    assert [r.name for r in f_proj.repos] == ["r1", "r2"]

    # Filter by single tag
    f_tag = filter_config(cfg, tags=["SHIP"])
    assert [r.name for r in f_tag.repos] == ["r1"]

    # Filter by repeated tags (AND logic)
    f_and = filter_config(cfg, tags=["thesis", "ship"])
    assert [r.name for r in f_and.repos] == ["r1"]

    # Filter by project AND tags
    f_comb = filter_config(cfg, project="thesis", tags=["sampling"])
    assert [r.name for r in f_comb.repos] == ["r2"]

    # Order preservation
    assert [r.name for r in f_proj.repos] == ["r1", "r2"]

    # No match raises FilterNoMatchError with known projects and tags
    with pytest.raises(FilterNoMatchError) as exc_info:
        filter_config(cfg, project="nonexistent")
    err_text = str(exc_info.value)
    assert "No repositories matched requested filters" in err_text
    assert "Known projects: apolo, thesis" in err_text
    assert "Known tags: apolo, ml, rag, sampling, ship, thesis" in err_text
