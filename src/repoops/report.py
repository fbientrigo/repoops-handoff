"""Report rendering for repoops snapshots."""

from rich.console import Console
from rich.table import Table

from repoops.git_scan import RepoSnapshot, Snapshot


def _repo_should_render(repo: RepoSnapshot, *, include_clean_repos: bool) -> bool:
    return include_clean_repos or repo.dirty or not repo.exists or not repo.is_git_repo


def render_markdown(snapshot: Snapshot, *, include_clean_repos: bool = True) -> str:
    """Render a Markdown report from a snapshot."""
    lines: list[str] = []
    lines.append("# repoops report")
    lines.append("")
    lines.append(f"- Schema: `{snapshot.schema_version}`")
    lines.append(f"- Machine: `{snapshot.machine}`")
    lines.append(f"- Timestamp: `{snapshot.timestamp}`")
    lines.append(f"- Repositories scanned: `{len(snapshot.repos)}`")
    lines.append("")

    dirty_count = sum(1 for repo in snapshot.repos if repo.dirty)
    missing_count = sum(1 for repo in snapshot.repos if not repo.exists)
    non_git_count = sum(1 for repo in snapshot.repos if repo.exists and not repo.is_git_repo)
    clean_omitted = sum(
        1 for repo in snapshot.repos if not _repo_should_render(repo, include_clean_repos=include_clean_repos)
    )

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Dirty repos: `{dirty_count}`")
    lines.append(f"- Missing repos: `{missing_count}`")
    lines.append(f"- Non-Git directories: `{non_git_count}`")
    if clean_omitted:
        lines.append(f"- Clean repos omitted: `{clean_omitted}`")
    lines.append("")

    lines.append("## Repositories")
    lines.append("")
    for repo in snapshot.repos:
        if not _repo_should_render(repo, include_clean_repos=include_clean_repos):
            continue
        lines.extend(_render_repo(repo))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_repo(repo: RepoSnapshot) -> list[str]:
    lines: list[str] = []
    lines.append(f"### {repo.name}")
    lines.append("")
    lines.append(f"- Path: `{repo.path}`")
    lines.append(f"- Exists: `{repo.exists}`")
    lines.append(f"- Git repo: `{repo.is_git_repo}`")
    lines.append(f"- Branch: `{repo.branch or 'n/a'}`")
    lines.append(f"- HEAD: `{repo.head or 'n/a'}`")
    lines.append(f"- Dirty: `{repo.dirty}`")
    lines.append(
        "- Counts: "
        f"modified=`{repo.counts.modified}`, "
        f"staged=`{repo.counts.staged}`, "
        f"untracked=`{repo.counts.untracked}`, "
        f"deleted=`{repo.counts.deleted}`, "
        f"renamed=`{repo.counts.renamed}`, "
        f"conflicted=`{repo.counts.conflicted}`"
    )
    lines.append("- Risk flags: " + (", ".join(f"`{flag}`" for flag in repo.risk_flags) or "none"))
    if repo.notable_files:
        lines.append("- Notable files:")
        lines.extend(f"  - `{path}`" for path in repo.notable_files)
    return lines


def print_summary_table(snapshot: Snapshot, *, console: Console | None = None) -> None:
    """Print a concise Rich terminal table."""
    console = console or Console()
    table = Table(title=f"repoops — {snapshot.machine}")
    table.add_column("Repo")
    table.add_column("State")
    table.add_column("Branch")
    table.add_column("HEAD")
    table.add_column("Counts")
    table.add_column("Risk")

    for repo in snapshot.repos:
        if not repo.exists:
            state = "missing"
        elif not repo.is_git_repo:
            state = "not git"
        elif repo.dirty:
            state = "dirty"
        else:
            state = "clean"

        counts = (
            f"M:{repo.counts.modified} "
            f"S:{repo.counts.staged} "
            f"U:{repo.counts.untracked} "
            f"D:{repo.counts.deleted} "
            f"R:{repo.counts.renamed} "
            f"C:{repo.counts.conflicted}"
        )
        table.add_row(
            repo.name,
            state,
            repo.branch or "-",
            repo.head or "-",
            counts,
            ", ".join(repo.risk_flags) or "-",
        )

    console.print(table)
