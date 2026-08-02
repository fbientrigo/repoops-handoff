# repoops-handoff

Low-noise multi-repository status and coding-agent handoff CLI.

`repoops-handoff` helps developers working across multiple local Git repositories answer two daily questions:

1. **Which repositories need my attention?** (dirty worktrees, uncommitted changes, untracked files, ahead/behind status)
2. **What context should I hand off to a coding agent?** (safe, reproducible checkpoints for tools like Antigravity, Claude Code, Codex, Aider, or OpenHands)

---

## Installation

Install using `pipx` (recommended for standalone CLI usage):

```bash
pipx install repoops-handoff
```

Or install for local development:

```bash
python -m venv .venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
# .venv\Scripts\Activate.ps1

pip install -e ".[dev]"
```

---

## 60-Second Quick Start

Create a configuration file at `~/.config/repoops/repos.yaml`:

```yaml
machine:
  name: dev-laptop

repos:
  - name: thesis-core
    path: ~/Documents/thesis/core
    project: thesis
    tags:
      - thesis
      - physics

  - name: charge-monitor
    path: ~/code/charge_monitoring
    project: system
    tags:
      - charge-monitoring
      - embedded
```

Scan all configured repositories:

```bash
repoops scan
```

---

## Default Configuration Location

Commands that inspect multiple repositories (`scan`, `run`, `notify`, `worklog-scan`, `worklog-weekly`, `worklog-export`) automatically resolve configuration using this exact precedence:

1. Explicit command-line flag: `--config /path/to/config.yaml` (or `-c`);
2. Environment variable: `REPOOPS_CONFIG=/path/to/config.yaml`;
3. Default path: `~/.config/repoops/repos.yaml`.

If no configuration file is found, `repoops` exits non-zero with a clear error message identifying the checked default path and how to provide one.

### Example Configuration

```yaml
machine:
  name: dev-station

defaults:
  max_files_per_repo: 12
  include_untracked: true
  include_clean_repos: false
  report_dir: ~/.local/share/repoops/reports
  snapshot_dir: ~/.local/share/repoops/snapshots
  worklog_db: ~/.local/share/repoops/worklog.db
  remote_check: true
  fetch: false
  fetch_timeout_seconds: 20

notifications:
  enabled: false
  channel: none

repos:
  - name: ship-adaptive-muon-bg
    path: ~/Documents/FisicoFabi/tesis/ship_adaptive_muon_bg
    project: thesis
    tags:
      - thesis
      - ship
      - ml
      - sampling
```

---

## Projects and Tags

Repositories can be classified using primary projects and secondary tags:

* **`project`**: A single primary workstream (string). Used for high-level grouping and daily worklog evidence aggregation.
* **`tags`**: Multiple secondary classifications (`list[str]`). Used for fine-grained multi-criteria filtering across repositories.

Recommended convention is lowercase kebab-case (e.g. `charge-monitoring`, `ship`). When matching filters on the CLI, whitespace is trimmed and comparisons are case-insensitive. Empty tags are rejected and tags are automatically deduplicated while preserving order.

### Filter Options

`scan`, `run`, and `worklog-scan` accept `--project` and `--tag` options:

```bash
# Scan all configured repositories
repoops scan

# Scan only repositories matching the primary project 'thesis'
repoops scan --project thesis

# Scan repositories containing the tag 'ship'
repoops scan --tag ship

# Scan repositories containing BOTH tags 'thesis' AND 'ml'
repoops scan --tag thesis --tag ml

# Filter by project AND tag
repoops scan --project thesis --tag ml
```

Filtering is applied before repository scanning begins, so excluded repositories do not trigger filesystem or Git operations. If no repositories match the requested filters, `repoops` exits non-zero and lists known projects and tags.

---

## Checkpoint and Resume Workflow

`repoops checkpoint` and `repoops resume` provide a config-free handoff workflow inside any single Git repository:

```bash
cd /path/to/your/repo

# 1. End of session: write a deterministic handoff checkpoint.
repoops checkpoint .
# Generates:
#   .repoops/handoff.json   (canonical source of truth)
#   .repoops/HANDOFF.md     (generated Markdown rendering — do not hand-edit)

# 2. Fill in human/agent notes in .repoops/handoff.json (goal, scope, decisions, next_action).
#    Re-run checkpoint to refresh Git facts while preserving your semantic content:
repoops checkpoint .

# 3. Share .repoops/HANDOFF.md with your coding agent session.

# 4. Next session (or fresh clone/machine): validate state before continuing.
repoops resume .
```

### Semantic Preservation

Repeated `repoops checkpoint .` calls automatically preserve existing human/agent notes (`semantic` fields and `next_action`) while refreshing Git facts (branch, HEAD, dirty counts, notable files, recent commits, timestamp).

Use `repoops checkpoint . --reset-semantic` to intentionally discard previous semantic context and re-seed `TODO:` placeholders.

### Resume & Drift Detection

`repoops resume` evaluates repository state against `.repoops/handoff.json`:

* **`NONE`**: Perfect match; safe to continue.
* **`WARNING`**: Non-fatal changes detected (e.g. minor uncommitted diffs or repository relocation with matching remote identity).
* **`BLOCKING`**: Fatal mismatch (e.g. different branch, uncommitted commit changes, or checkpoint belongs to a different repository). Exits non-zero.

---

## Safety Guarantees

`repoops-handoff` is strictly read-only by default and adheres to tight safety rules:

1. **No Mutating Git Operations**: `repoops` never runs `git pull`, `git push`, `git reset`, `git checkout`, `git switch`, or `git clean`.
2. **Safe Fetch Only**: `git fetch --prune` is executed only if `--fetch` is explicitly passed or `defaults.fetch: true` is configured. It only updates local remote-tracking refs without altering the working tree or current branch.
3. **No File Content Harvesting**: Handoff scanning reads file paths, status flags, and `git diff --stat` counters. It never reads full file contents, source code, or diff contents.
4. **Secret Redaction**: File paths matching secret patterns (e.g. `.env`, `id_rsa`, `*.pem`, `credentials.json`) are flagged as `possible_secret_file` and redacted from output reports.
5. **Only Allowlisted Git Commands**: Git metadata collection relies exclusively on 6 read-only `git` subcommands:
   * `git rev-parse`
   * `git status --porcelain=v2`
   * `git log`
   * `git diff`
   * `git rev-list`
   * `git config --get remote.origin.url`

---

## Command Reference

### `repoops --version`

Print the version (`repoops 0.1.0`) and exit.

### `repoops scan`

```bash
repoops scan [--config PATH] [--project PROJECT] [--tag TAG] [--fetch]
```

Scans configured repositories and displays a terminal summary table of dirty files, branch, HEAD, ahead/behind status, and attention scores.

### `repoops run`

```bash
repoops run [--config PATH] [--project PROJECT] [--tag TAG] [--fetch]
```

Scans configured repositories, writes JSON snapshot (`repoops-snapshot-*.json`) and Markdown report (`repoops-report-*.md`), and sends configured notifications.

### `repoops notify`

```bash
repoops notify [--config PATH] --report PATH
```

Sends an existing Markdown report to configured notification channels (e.g. Telegram).

### `repoops checkpoint`

```bash
repoops checkpoint [PATH] [--reset-semantic]
```

Writes `.repoops/handoff.json` and `.repoops/HANDOFF.md` for the repository at `PATH` (defaults to `.`). Preserves existing semantic context unless `--reset-semantic` is supplied.

### `repoops resume`

```bash
repoops resume [PATH]
```

Inspects current repository state against `.repoops/handoff.json` at `PATH` (defaults to `.`) and prints a continuation report. Exits non-zero on `BLOCKING` drift.

### `repoops worklog-scan`

```bash
repoops worklog-scan [--config PATH] [--project PROJECT] [--tag TAG]
```

Scans configured repositories and records a worklog evidence snapshot into the local SQLite database (`worklog_db`).

### `repoops worklog-weekly`

```bash
repoops worklog-weekly [--config PATH] --week YYYY-Www
```

Prints candidate worklog evidence rows for a given ISO week.

### `repoops worklog-export`

```bash
repoops worklog-export [--config PATH] --month YYYY-MM [--format csv]
```

Exports candidate worklog evidence rows for a given month as a CSV file.

---

## Development and Release Information

### Local Quality Gate

Before committing code or opening a pull request, run the complete local quality gate:

```bash
# 1. Lint checks
ruff check .

# 2. Code formatting verification
ruff format --check .

# 3. Unit and integration tests
pytest

# 4. Build distribution packages (sdist and wheel)
python -m build

# 5. Validate package metadata and distributions
python -m twine check dist/*
```

---

## Telegram Notifications

`channel: telegram` delivers a short summary of dirty repositories directly to Telegram.

1. Create a bot via [@BotFather](https://t.me/BotFather) and receive a bot token.
2. Obtain your numeric Chat ID.
3. Export environment variables before executing `repoops`:

```bash
export REPOOPS_TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57"
export REPOOPS_TELEGRAM_CHAT_ID="123456789"
```

4. Configure `notifications.enabled: true` and `notifications.channel: telegram` in `repos.yaml`.

---

## Worklog Evidence

`repoops worklog-scan`, `worklog-weekly`, and `worklog-export` provide conservative, low-confidence worklog evidence to assist with manual timesheet drafting.

* **What it proves**: That uncommitted worktree activity occurred on a project on specific dates.
* **What it does NOT prove**: Exact hours worked, code quality, or billable completion.
* **Human Approval Required**: Every exported value (`suggested_reportable_hours`) is capped at 4 hours/day and must be reviewed and approved by a human before billing or reporting.

---

## License

This project is licensed under the terms of the MIT License. See [LICENSE](LICENSE) for details.
