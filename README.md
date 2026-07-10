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

Safe fetch, ahead/behind status, and an attention score are landed. Multi-machine snapshot comparison is still out of scope.

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
  worklog_db: ~/.local/share/repoops/worklog.db  # see "Worklog evidence" below
  remote_check: true      # compute upstream/ahead/behind from local refs
  fetch: false             # true permits `git fetch --prune` before computing ahead/behind
  fetch_timeout_seconds: 20

notifications:
  enabled: false
  channel: none  # telegram | slack | email | none
  # channel: telegram requires REPOOPS_TELEGRAM_BOT_TOKEN and
  # REPOOPS_TELEGRAM_CHAT_ID in the environment — see "Telegram notifications" below.

repos:
  - name: dihiggs
    path: ~/dihiggs
    project: DiHiggs   # optional; groups repos for worklog evidence

  - name: aws-climate
    path: ~/aws

  - name: apolo-rag
    path: ~/apolo_rag
    project: Apolo

  - name: vectorjobs
    path: ~/vectorjobs
```

## Planned CLI

```bash
repoops scan --config examples/repos.yaml
repoops scan --config examples/repos.yaml --fetch
repoops run --config examples/repos.yaml
repoops run --config examples/repos.yaml --fetch
repoops notify --config examples/repos.yaml --report ~/.local/share/repoops/reports/latest.md
repoops worklog-scan --config examples/repos.yaml
repoops worklog-weekly --config examples/repos.yaml --week 2026-W28
repoops worklog-export --config examples/repos.yaml --month 2026-07 --format csv
```

### `repoops scan`

Scans configured repositories and prints a concise terminal table, including `Ahead`/`Behind`/`Score` columns.

### `repoops run`

Runs the full workflow:

1. scan repositories;
2. write JSON snapshot;
3. write Markdown report (with an "Attention summary" sorted by score);
4. optionally send notification.

### `repoops notify`

Sends an already-generated report through the configured notification backend.

### `repoops worklog-scan` / `worklog-weekly` / `worklog-export`

Record and summarize worklog evidence from repeated scans. See "Worklog evidence" below for what these can and cannot prove.

### `--fetch`

Both `scan` and `run` accept `--fetch` to force a safe `git fetch --prune` before computing ahead/behind status. It only updates local remote-tracking refs — never the working tree, never `git pull`. Without `--fetch`, the config default (`defaults.fetch`, `false` unless set) applies. See `docs/CLI_CONTRACT.md` and `docs/SAFETY_CONTRACT.md` for the full contract.

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

This is the actual message body sent to Telegram: the report's header, Summary, and Attention summary sections, verbatim, with the per-repo detail section dropped.

```text
# repoops report

- Schema: `repoops.snapshot.v1`
- Machine: `nasapcdeb`
- Timestamp: `2026-06-25T09:00:00-04:00`
- Repositories scanned: `4`

## Summary

- Dirty repos: `2`
- Missing repos: `0`
- Non-Git directories: `0`

## Attention summary

| Repo | Score | Branch | HEAD | Ahead | Behind | Risk flags |
| --- | --- | --- | --- | --- | --- | --- |
| dihiggs | 40 | main | a1b2c3d | 2 | 0 | `dirty`, `ahead_remote` |
| aws-climate | 30 | main | e4f5g6h | 0 | 0 | `dirty` |
```

## Telegram notifications

`channel: telegram` sends a short synthesis (header + Summary + Attention summary — never the per-repo detail section) as a single Telegram message, so a phone push notification stays small even for many repos.

1. Create a bot with [@BotFather](https://t.me/BotFather) and note the bot token.
2. Message the bot once (or add it to a group) and find your numeric chat ID, e.g. via `https://api.telegram.org/bot<token>/getUpdates`.
3. Export both values in the environment `repoops` runs under — never in the YAML config:

```bash
export REPOOPS_TELEGRAM_BOT_TOKEN="123456:AA...."
export REPOOPS_TELEGRAM_CHAT_ID="123456789"
```

4. Set `notifications.enabled: true` and `notifications.channel: telegram` in config, then run `repoops run --config ...` (or `repoops notify --config ... --report <path>` against an existing report).

If either environment variable is missing, `repoops notify`/`repoops run` fail loudly with a clear error naming the missing variable (never its value) so a misconfigured cron job or systemd timer surfaces immediately. A failed Telegram API call (bad token, network unreachable) is non-fatal — it's reported as `skipped` with a sanitized reason, the same way a failed `git fetch` is non-fatal to the rest of a scan.

## Snapshot Schema

```json
{
  "schema_version": "repoops.snapshot.v1",
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
        "ahead_remote"
      ],
      "remote": {
        "has_upstream": true,
        "upstream": "origin/main",
        "ahead": 2,
        "behind": 0,
        "fetched": false,
        "fetch_error": null
      },
      "attention_score": 40
    }
  ]
}
```

## Risk Flags

`repoops` classifies simple risk flags without using an LLM:

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
* `ahead_remote`
* `behind_remote`
* `diverged_remote`
* `no_upstream`
* `fetch_failed`

## Cron Example

```cron
# Every 15 minutes, low-noise: no network access, local refs only.
*/15 * * * * /usr/bin/env repoops run --config /home/fabian/.config/repoops/repos.yaml

# Once an hour, refresh remote-tracking refs before computing ahead/behind.
0 * * * * /usr/bin/env repoops run --config /home/fabian/.config/repoops/repos.yaml --fetch
```

By default `repoops` never touches the network — `defaults.fetch` is `false` and `--fetch` must be passed explicitly (or set in config) to permit `git fetch --prune`. Every other run is entirely local, read-only Git metadata inspection.

If `notifications.channel: telegram` is enabled, `cron` does not source your shell profile, so `REPOOPS_TELEGRAM_BOT_TOKEN`/`REPOOPS_TELEGRAM_CHAT_ID` must be set where cron can see them — either as `crontab` environment lines, or in a wrapper script:

```cron
REPOOPS_TELEGRAM_BOT_TOKEN=123456:AA....
REPOOPS_TELEGRAM_CHAT_ID=123456789

*/15 * * * * /usr/bin/env repoops run --config /home/fabian/.config/repoops/repos.yaml
```

Keep the crontab file `chmod 600` (owner read/write only) since it now holds a credential-equivalent value.

## Windows (PowerShell / Task Scheduler)

```powershell
# No-fetch, local refs only:
repoops run --config C:\Users\fabian\.config\repoops\repos.yaml

# Refresh remote-tracking refs before computing ahead/behind:
repoops run --config C:\Users\fabian\.config\repoops\repos.yaml --fetch
```

Register either line as the action of a Windows Task Scheduler task (Trigger: e.g. "Daily, repeat every 15 minutes") instead of cron. `repoops` exits `0` on a completed scan and writes no output beyond the printed table and the JSON/Markdown artifacts, so it is safe to run non-interactively from a scheduled task.

For Telegram notifications, set the two environment variables at the user level (`setx REPOOPS_TELEGRAM_BOT_TOKEN "123456:AA...."`, `setx REPOOPS_TELEGRAM_CHAT_ID "123456789"`) so Task Scheduler's non-interactive session inherits them; `setx` only takes effect in new sessions, so re-register the task (or reboot) after setting them.

## Worklog evidence

`repoops` can turn repeated local scan snapshots into low-confidence **worklog evidence** — never a final report, never exact hours. This is an M0: minimal, local, read-only, and every output row is a candidate for you to review, not a conclusion.

### What it can prove

- That a repo had uncommitted local changes at a given scan time.
- That a project (repos grouped by `repos[].project` in config, e.g. `Apolo`, `ChargeMonitoringSystem`, `DiHiggs`) had **repeated** dirty-worktree activity on a given day — weak but real evidence that someone was working on it that day.

### What it cannot prove

- Exact hours worked. `repoops` never outputs a precise duration — only a wide `real_hours_estimate_range` and a `suggested_reportable_hours` value capped at 4 hours/day.
- That changes are complete, correct, reviewed, or even related to billable work.
- Time spent away from a dirty worktree — planning, meetings, review, and reading-only days never create a candidate, since a clean scan is not evidence.
- *What* changed. File contents and diffs are never read or stored; only redacted paths, counts, and risk flags.

### How estimation works (conservative, by design)

- One isolated dirty snapshot on a day → `confidence: low`.
- Repeated dirty snapshots on the same day/project push confidence to `medium`/`high` and raise `suggested_reportable_hours`, but it never exceeds 4 hours/day, no matter how many snapshots were taken.
- If the same repo shows the same redacted diff, dirty, across 3+ different days in a trailing week, the candidate is flagged `needs_review: true` — that pattern is as consistent with a stale uncommitted change as with real multi-day work, so it's left for you to judge.

### Scheduling scans

Schedule `repoops worklog-scan` the same way as `repoops run` (see "Cron Example" / "Windows" above), ideally more frequently during working hours so there's enough repeated-activity signal to estimate from:

```cron
# Every 30 minutes, working hours, weekdays only.
*/30 9-19 * * 1-5 /usr/bin/env repoops worklog-scan --config /home/fabian/.config/repoops/repos.yaml
```

```powershell
repoops worklog-scan --config C:\Users\fabian\.config\repoops\repos.yaml
```

It never runs `git fetch` and only reuses the same read-only scan `repoops run` already performs — see `docs/SAFETY_CONTRACT.md`.

### Feeding the weekly pack to Claude Tasks

`repoops worklog-weekly --week 2026-W28` prints candidate rows to the terminal; `repoops worklog-export --month 2026-07 --format csv` writes them to a CSV under `defaults.report_dir`. Paste that CSV (or the printed table) into a Claude Tasks prompt alongside your own memory of the week and ask it to draft a timesheet **for your review**, e.g.:

> Here's my repoops worklog CSV for the week of 2026-07-06. Cross-reference it with what I remember doing and draft a timesheet entry per day. Flag anything `needs_review` for me to double-check before I submit it.

`repoops` only produces the raw evidence rows — it never talks to Claude Tasks (or any other system) itself, and it never generates a monthly report of its own (that's explicitly out of scope for M0).

### Human approval required

**No `suggested_reportable_hours` value is ever a final answer.** Every worklog row is a candidate that a human must confirm, adjust, or reject before it goes into any invoice, timesheet, or payroll system.

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

* Add Telegram notification. ✅
* Add Slack webhook notification.
* Add SMTP email notification.

### v0.3

* Add systemd timer example.
* Add cron example.

### v0.4

* Validate the same workflow on a second machine.

## Future Roadmap

### v1

* Safe `git fetch`. ✅
* Ahead/behind status. ✅
* Attention score and updated reports. ✅
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

