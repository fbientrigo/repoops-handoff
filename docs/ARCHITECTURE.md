# Architecture — repoops v0

## Runtime flow

```text
YAML config
    |
    v
repoops.config.load_config
    |
    v
repoops.git_scan.build_snapshot
    |
    +--> repoops.git_scan.scan_repo(repo A)
    +--> repoops.git_scan.scan_repo(repo B)
    +--> repoops.git_scan.scan_repo(repo N)
    |
    v
Snapshot model
    |
    +--> repoops.report.print_summary_table
    +--> repoops.report.render_markdown
    +--> JSON snapshot writer
    |
    v
repoops.notify.notify_report
```

## Dependency direction

```text
cli
 ├── config
 ├── git_scan
 ├── report
 └── notify

git_scan
 ├── config
 └── paths

report
 └── git_scan data models

notify
 └── config
```

`config` and `paths` should remain low-level and have no dependency on Git, Rich, Typer, or HTTP clients.

## Why no database in v0

v0 artifacts are timestamped JSON and Markdown files. This is enough for:

- terminal review;
- notification payloads;
- historical snapshots;
- future handoff generation.

A database would add state, migrations, and failure modes before the product has proven value.

## Why no agents in v0

The tool is intentionally a status collector first. Agent handoff generation belongs in later stages after the snapshot contract is stable.
