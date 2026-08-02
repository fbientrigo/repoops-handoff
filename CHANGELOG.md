# Changelog

All notable changes to `repoops-handoff` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-01

### Added

* **Multi-repository scanning**: Scans configured local repositories for branch names, HEAD commits, dirty worktrees, and porcelain v2 status counts.
* **Risk and attention reporting**: Automated risk classification (`dirty`, `untracked_files`, `possible_secret_file`, `ahead_remote`, `behind_remote`, etc.) and non-LLM attention score calculation.
* **Safe local ahead/behind inspection**: Computes upstream divergence from local tracking refs by default. Accepts optional `--fetch` flag (or `defaults.fetch: true` config) to execute safe `git fetch --prune` without mutating working trees.
* **Checkpoint & Resume workflow**: Config-free single-repository handoff generation (`repoops checkpoint .`) creating canonical `.repoops/handoff.json` and rendered `.repoops/HANDOFF.md`, with validation on continuation (`repoops resume .`).
* **Semantic preservation**: Repeat `repoops checkpoint` runs preserve existing goal, scope, decisions, failed attempts, verification notes, and next action while refreshing Git facts. Added `--reset-semantic` to re-seed `TODO:` placeholders.
* **Repository relocation checks**: Remote origin identity matching ensures repository relocation (e.g. across containers or clone directories) surfaces as a `WARNING` rather than `BLOCKING` drift.
* **Project and Tag filters**: Repeatable `--tag` and `--project` CLI options on `scan`, `run`, and `worklog-scan` to filter scanned repositories with case-insensitive, whitespace-trimmed, AND-matching logic.
* **Default configuration discovery**: Automatic resolution order: 1. `--config/-c`, 2. `REPOOPS_CONFIG` env var, 3. `~/.config/repoops/repos.yaml`. Clear non-zero exit error when no config file is found.
* **Worklog evidence**: Read-only SQLite worklog tracking (`repoops worklog-scan`), weekly summary view (`worklog-weekly`), and CSV export (`worklog-export`).
* **Telegram notifications**: Optional synthesis report publishing to Telegram using stdlib HTTP client and env-var credentials.
* **CLI Version Command**: Added `repoops --version` reporting package version via `importlib.metadata`.

### Security & Safety Limitations

* Read-only Git metadata extraction restricted to 6 allowlisted subcommands (`rev-parse`, `status`, `log`, `diff`, `rev-list`, `config --get remote.origin.url`).
* No mutating Git commands (`pull`, `push`, `reset`, `clean`, `checkout`, `switch`).
* No full file contents or diff bodies collected or transmitted; secret-like file paths redacted.
