from repoops.git_scan import ChangeCounts, RepoSnapshot, Snapshot
from repoops.report import render_markdown


def test_markdown_report_contains_summary() -> None:
    snapshot = Snapshot(
        machine="nasapcdeb",
        timestamp="2026-06-25T09:00:00-04:00",
        repos=[
            RepoSnapshot(
                name="dihiggs",
                path="/home/fabian/dihiggs",
                exists=True,
                is_git_repo=True,
                branch="main",
                head="a1b2c3d",
                dirty=True,
                counts=ChangeCounts(modified=1, untracked=1),
                notable_files=["src/model.py"],
                risk_flags=["dirty", "untracked_files"],
            )
        ],
    )

    markdown = render_markdown(snapshot)

    assert "repoops.snapshot.v0" in markdown
    assert "nasapcdeb" in markdown
    assert "dihiggs" in markdown
    assert "main" in markdown
    assert "a1b2c3d" in markdown
    assert "modified=`1`" in markdown
    assert "dirty" in markdown


def test_markdown_report_omits_clean_repos_when_configured() -> None:
    snapshot = Snapshot(
        machine="nasapcdeb",
        timestamp="2026-06-25T09:00:00-04:00",
        repos=[
            RepoSnapshot(
                name="clean-repo",
                path="/tmp/clean",
                exists=True,
                is_git_repo=True,
                dirty=False,
            )
        ],
    )

    markdown = render_markdown(snapshot, include_clean_repos=False)

    assert "Clean repos omitted: `1`" in markdown
    assert "### clean-repo" not in markdown


def test_markdown_report_does_not_include_secret_like_paths() -> None:
    snapshot = Snapshot(
        machine="nasapcdeb",
        timestamp="2026-06-25T09:00:00-04:00",
        repos=[
            RepoSnapshot(
                name="repo",
                path="/tmp/repo",
                exists=True,
                is_git_repo=True,
                dirty=True,
                notable_files=["[REDACTED_SECRET_PATH]", "config/[REDACTED_SECRET_PATH]"],
                risk_flags=["dirty", "possible_secret_file"],
            )
        ],
    )

    markdown = render_markdown(snapshot)

    assert "[REDACTED_SECRET_PATH]" in markdown
    assert ".env" not in markdown
    assert "api_token" not in markdown
    assert "credentials.json" not in markdown


def test_markdown_report_does_not_include_file_contents() -> None:
    secret_content = "SUPER_SECRET_VALUE_SHOULD_NOT_APPEAR"
    snapshot = Snapshot(
        machine="nasapcdeb",
        timestamp="2026-06-25T09:00:00-04:00",
        repos=[
            RepoSnapshot(
                name="repo",
                path="/tmp/repo",
                exists=True,
                is_git_repo=True,
                dirty=True,
                notable_files=["src/model.py"],
                risk_flags=["dirty"],
            )
        ],
    )

    markdown = render_markdown(snapshot)

    assert secret_content not in markdown
