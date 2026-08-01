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

### `repoops checkpoint` / `repoops resume` (single-repo, config-free)

```text
PATH (defaults to ".")
    |
    v
repoops.handoff.discover_repo_root      (git rev-parse --show-toplevel)
    |
    v
repoops.handoff.collect_repository_facts
    |
    +--> reuses repoops.git_scan._run_git / parse_porcelain_status /
    |    redact_secret_like_path / _notable_files / _remote_sync_status(fetch=False)
    |
    v
RepositoryInfo + ChangesInfo + recent commits
    |
    checkpoint:                              resume:
    v                                         v
Handoff (schema_version=repoops.handoff.v1)   load + validate .repoops/handoff.json
    |                                         |
    v                                         v
repoops.handoff_render.render_handoff_markdown   repoops.handoff._compute_drift
    |                                         |
    v                                         v
.repoops/handoff.json + .repoops/HANDOFF.md   repoops.handoff_render.render_resume_report
(atomic_write_text; the only writes            |
 repoops performs anywhere)                    v
                                               stdout (RECORDED HANDOFF / CURRENT
                                               REPOSITORY STATE / DRIFT DETECTED /
                                               NEXT ACTION), exit 1 if BLOCKING
```

This path is independent of `repoops scan`/`run`/`notify`/`worklog-*`: no YAML
config, no multi-repo loop, no notification backend. It scans exactly the one
repository containing `PATH`.

## Dependency direction

```text
cli
 ├── config
 ├── git_scan
 ├── report
 ├── notify
 ├── handoff
 └── handoff_render

git_scan
 ├── config
 └── paths

report
 └── git_scan data models

notify
 ├── config
 ├── paths
 └── telegram

telegram
 (no repoops dependencies — stdlib urllib only)

handoff
 ├── git_scan (_run_git, parse_porcelain_status, redact_secret_like_path,
 │             _notable_files, _remote_sync_status — reused, not duplicated)
 ├── handoff_models
 ├── handoff_render
 └── paths (atomic_write_text, ensure_dir)

handoff_render
 └── handoff_models

handoff_models
 └── git_scan (ChangeCounts — reused, not duplicated)
```

`config` and `paths` should remain low-level and have no dependency on Git, Rich, Typer, or HTTP clients. `telegram` is the one module allowed to depend on an HTTP client (stdlib `urllib`, deliberately no third-party dependency); it depends on nothing else in `repoops` and knows only "send this text to this chat with this token," so it's just as easy to swap for `httpx`/`requests` later or reuse from a future Slack/SMTP backend without pulling in `notify`'s config-handling concerns.

## Why no database in v0

v0 artifacts are timestamped JSON and Markdown files. This is enough for:

- terminal review;
- notification payloads;
- historical snapshots;
- future handoff generation.

A database would add state, migrations, and failure modes before the product has proven value.

## Why no agents in v0

The tool is intentionally a status collector first. Agent handoff generation belongs in later stages after the snapshot contract is stable.

**P0 update:** `repoops checkpoint`/`repoops resume` (see above) are the first
handoff-generation stage referenced by this note, landed once the `repoops.snapshot.v1`
contract had proven stable. They remain a deterministic Git-facts collector, not an
agent: no LLM call happens inside `repoops` anywhere in `repoops.handoff`. Turning
the generated `HANDOFF.md`/`handoff.json` into an actual coding-agent session is
still an explicit, external, human-initiated step (paste the file into Codex/Claude
Code/Gemini/etc.) — `repoops` does not invoke or drive any agent itself. Target-specific
renderers (`--target codex`, etc.), automatic LLM-generated summaries, and autonomous
agent execution remain out of scope; see README "Scope control".
