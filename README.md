# repoops-handoff

Low-noise multi-repository status reporter and agent handoff generator for reducing context switching across machines.

## Purpose

`repoops-handoff` helps developers who work across many repositories and machines answer a simple daily question:

> Which repositories need my attention, and what context should I hand off to a coding agent?

The project starts intentionally small. Version 0 focuses only on detecting dirty Git worktrees across configured local repositories and delivering a concise report through terminal output and optional notifications.

The long-term goal is to provide safe, reproducible handoffs for terminal-based coding agents such as Antigravity, Codex, Claude Code, Aider, OpenHands, or similar tools.

## Motivation

When working across multiple projects, machines, and agents, context switching becomes expensive:

* Which repository was I editing?
* Which machine has dirty worktrees?
* Did I leave staged changes somewhere?
* Are there untracked files I forgot?
* Which files changed?
* What should I give to an agent so it can help without me re-explaining everything?

`repoops-handoff` is designed to reduce that friction by producing small, structured, low-noise reports.

## Development Philosophy

This project follows a staged progression:

```text
skateboard -> bicycle -> motorcycle -> car
```

Each stage must deliver real value before adding complexity.

### v0: Skateboard

Detect dirty worktrees and deliver a concise report.

### v1: Bicycle

Add safe fetch, ahead/behind status, and multi-machine snapshots.

### v2: Motorcycle

Add allowlisted tests, artifact scanning, and dependency drift checks.

### v3: Car

Add CI inspection and agent handoff generation.

### v4: Assisted car

Allow controlled agent execution under strict safety boundaries.

## v0 Scope

Version 0 is intentionally conservative.

It should:

* read a configurable list of local repositories;
* detect whether each repository exists;
* detect whether each path is a Git repository;
* report the current branch;
* report the short HEAD commit;
* detect dirty worktrees;
* count staged, modified, untracked, deleted, renamed, and conflicted files;
* list a small number of notable changed files;
* generate a JSON snapshot;
* generate a Markdown report;
* optionally send a short notification through Telegram, Slack, or email.

## v0 Non-goals

Version 0 must not:

* run `git pull`;
* run `git push`;
* run `git reset`;
* run `git clean`;
* run tests;
* inspect CI;
* execute coding agents;
* read file contents unnecessarily;
* send full diffs;
* print or send secrets;
* mutate repositories.

## Example Configuration

```yaml
machine:
  name: nasapcdeb

defaults:
  max_files_per_repo: 12
  include_untracked: true
  include_clean_repos: false
  report_dir: ~/.local/share/repoops/reports
  snapshot_dir: ~/.local/share/repoops/snapshots

notifications:
  enabled: true
  channel: telegram  # telegram | slack | email | none

  telegram:
    bot_token_env: REPOOPS_TELEGRAM_BOT_TOKEN
    chat_id_env: REPOOPS_TELEGRAM_CHAT_ID

  slack:
    webhook_url_env: REPOOPS_SLACK_WEBHOOK_URL

  email:
    smtp_host_env: REPOOPS_SMTP_HOST
    smtp_port_env: REPOOPS_SMTP_PORT
    username_env: REPOOPS_SMTP_USERNAME
    password_env: REPOOPS_SMTP_PASSWORD
    from_env: REPOOPS_EMAIL_FROM
    to_env: REPOOPS_EMAIL_TO

repos:
  - name: dihiggs
    path: ~/dihiggs
    group: physics

  - name: aws-climate
    path: ~/aws
    group: cloud

  - name: apolo-rag
    path: ~/apolo_rag
    group: apolo

  - name: vectorjobs
    path: ~/vectorjobs
    group: apolo
```

## Planned CLI

```bash
repoops scan --config examples/repos.yaml
repoops run --config examples/repos.yaml
repoops notify --config examples/repos.yaml --report ~/.local/share/repoops/reports/latest.md
```

### `repoops scan`

Scans configured repositories and prints a concise terminal table.

### `repoops run`

Runs the full v0 workflow:

1. scan repositories;
2. write JSON snapshot;
3. write Markdown report;
4. optionally send notification.

### `repoops notify`

Sends an already-generated report through the configured notification backend.

## Example Terminal Output

```text
RepoOps v0 scan — nasapcdeb

Dirty repos: 2 / 4

dihiggs
  branch: main
  head: a1b2c3d
  status: DIRTY
  modified: 3
  untracked: 2
  staged: 0
  deleted: 0

aws-climate
  branch: main
  head: e4f5g6h
  status: DIRTY
  modified: 1
  untracked: 0
  staged: 1
  deleted: 0
```

## Example Notification

```text
RepoOps v0 — nasapcdeb

Dirty repos: 2 / 4

1. dihiggs [main @ a1b2c3d]
   M:3 U:2 S:0 D:0
   Notable: src/model.py, tests/test_model.py

2. aws-climate [main @ e4f5g6h]
   M:1 U:0 S:1 D:0
   Notable: lambda/handler.py

Report:
~/.local/share/repoops/reports/latest.md
```

## Snapshot Schema

```json
{
  "schema_version": "repoops.snapshot.v0",
  "machine": "nasapcdeb",
  "timestamp": "2026-06-25T09:00:00-04:00",
  "repos": [
    {
      "name": "dihiggs",
      "path": "/home/fabian/dihiggs",
      "exists": true,
      "is_git_repo": true,
      "branch": "main",
      "head": "a1b2c3d",
      "dirty": true,
      "counts": {
        "modified": 3,
        "staged": 0,
        "untracked": 2,
        "deleted": 0,
        "renamed": 0,
        "conflicted": 0
      },
      "notable_files": [
        "src/model.py",
        "tests/test_model.py"
      ],
      "risk_flags": [
        "dirty",
        "untracked_files",
        "source_changes"
      ]
    }
  ]
}
```

## Risk Flags

v0 should classify simple risk flags without using an LLM:

* `dirty`
* `staged_changes`
* `deleted_files`
* `many_changes`
* `untracked_files`
* `possible_secret_file`
* `dependency_file_changed`
* `ci_file_changed`
* `notebook_changed`
* `repo_missing`
* `not_git_repo`
* `detached_head`

## Safety Principles

`repoops-handoff` should be safe by default.

The tool should not mutate repositories unless a later version explicitly introduces an opt-in action.

In v0, the tool must only inspect repository state.

Notification output must avoid leaking secrets. It should never include file contents or full diffs. Secret-like paths should be redacted or flagged carefully.

## Suggested Stack

* Python
* Typer
* Rich
* Pydantic
* PyYAML
* HTTPX
* standard library `subprocess`
* pytest for tests
* ruff for linting

## Development Roadmap

### v0.0

* Load YAML config.
* Scan local repositories.
* Print terminal report.

### v0.1

* Write JSON snapshot.
* Write Markdown report.
* Maintain `latest.md` symlink or copy.

### v0.2

* Add Telegram notification.
* Add Slack webhook notification.
* Add SMTP email notification.

### v0.3

* Add systemd timer example.
* Add cron example.

### v0.4

* Validate the same workflow on a second machine.

## Future Roadmap

### v1

* Safe `git fetch`.
* Ahead/behind status.
* Multi-machine snapshot comparison.

### v2

* Allowlisted test commands.
* Artifact miner.
* Dependency drift checks.

### v3

* GitHub Actions inspection.
* CI failure summarization.
* Agent handoff Markdown generation.

### v4

* Optional controlled agent invocation.
* Strict dry-run by default.
* Explicit allowlists for patching.

