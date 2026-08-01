# Data contracts — repoops v1

## Changelog

- **v1**: added `remote` (`RemoteSyncStatus`) and `attention_score` to the repo snapshot; added 5 remote-related risk flags. `schema_version` bumped from `repoops.snapshot.v0` to `repoops.snapshot.v1`.
- **M0 worklog**: added a local SQLite evidence store (`repoops.worklog`) and derived candidate rows. This is additive — it does not change the JSON snapshot schema above.
- **P0 handoff**: added `repoops.handoff` (`repoops checkpoint`/`repoops resume`) and its own `repoops.handoff.v1` schema (`.repoops/handoff.json`), fully independent of the `repoops.snapshot.v1` schema above. See "Handoff schema (`repoops.handoff.v1`)" below.

## Snapshot schema

```json
{
  "schema_version": "repoops.snapshot.v1",
  "machine": "nasapcdeb",
  "timestamp": "2026-06-25T09:00:00-04:00",
  "repos": []
}
```

Required fields:

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | string | Must equal `repoops.snapshot.v1`. |
| `machine` | string | From config `machine.name`. |
| `timestamp` | string | ISO-8601 with local timezone if available. |
| `repos` | array | List of repo snapshots. |

## Repo snapshot schema

| Field | Type | Notes |
| --- | --- | --- |
| `name` | string | Human-friendly repo name from config. |
| `path` | string | Expanded absolute path. |
| `exists` | bool | Whether path exists. |
| `is_git_repo` | bool | Whether path is inside a Git worktree. |
| `branch` | string/null | Current branch or `HEAD` when detached. |
| `head` | string/null | Short commit hash. |
| `dirty` | bool | Whether porcelain status has entries. |
| `counts` | object | Counts by change category. |
| `notable_files` | array[string] | Redacted relative paths, capped by config. |
| `risk_flags` | array[string] | Known v1 flags only. |
| `remote` | object | `RemoteSyncStatus`. Only populated when `defaults.remote_check` is enabled; otherwise all-default (`has_upstream=false`, others `null`/`false`). |
| `attention_score` | int | Deterministic priority score, see "Attention score" below. |

## Remote sync schema

```json
{
  "has_upstream": false,
  "upstream": null,
  "ahead": null,
  "behind": null,
  "fetched": false,
  "fetch_error": null
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `has_upstream` | bool | Whether the current branch has a tracking upstream (`@{u}` resolves). |
| `upstream` | string/null | e.g. `origin/main`. `null` when no upstream. |
| `ahead` | int/null | Commits on `HEAD` not on upstream (`git rev-list --count @{u}..HEAD`). `null` when no upstream or the count could not be determined. |
| `behind` | int/null | Commits on upstream not on `HEAD` (`git rev-list --count HEAD..@{u}`). `null` when no upstream or the count could not be determined. |
| `fetched` | bool | Whether `git fetch --prune` was attempted and succeeded for this repo during this scan. |
| `fetch_error` | string/null | Short, sanitized error message when a requested fetch failed. Never contains raw stderr, credentials, or full URLs. |

`ahead`/`behind` are computed from local refs (updated by `fetch` when requested); they never require network access themselves.

## Counts schema

```json
{
  "modified": 0,
  "staged": 0,
  "untracked": 0,
  "deleted": 0,
  "renamed": 0,
  "conflicted": 0
}
```

## Risk flags

Allowed v1 flags:

```text
dirty
staged_changes
deleted_files
many_changes
untracked_files
possible_secret_file
dependency_file_changed
ci_file_changed
notebook_changed
repo_missing
not_git_repo
detached_head
ahead_remote
behind_remote
diverged_remote
no_upstream
fetch_failed
```

No other risk flags should be emitted in v1 unless the schema version changes.

The 5 remote-related flags (`ahead_remote`, `behind_remote`, `diverged_remote`, `no_upstream`, `fetch_failed`) are only ever emitted when `defaults.remote_check` is enabled for the scan. `ahead_remote`/`behind_remote`/`diverged_remote` are independent, not mutually exclusive — a diverged repo carries all three.

## Attention score

`attention_score` (int, on each repo snapshot) is a pure, deterministic function of `risk_flags` and `counts.conflicted`, used to sort the Markdown "Attention summary" and the Rich table's `Score` column. Points are additive — every applicable row below contributes, so e.g. a diverged repo (`ahead_remote` + `behind_remote` + `diverged_remote` all present) scores higher than a simply-ahead repo.

| Condition | Points |
| --- | --- |
| `repo_missing` | 100 |
| `not_git_repo` | 90 |
| `counts.conflicted > 0` | 80 |
| `possible_secret_file` | 70 |
| `fetch_failed` | 65 |
| `deleted_files` | 50 |
| `diverged_remote` | 45 |
| `ahead_remote` | 40 |
| `behind_remote` | 35 |
| `dirty` | 30 |
| `many_changes` | 25 |
| `no_upstream` | 10 |
| `untracked_files` | 10 |
| clean repo | 0 |

Notes:

- Conflicts are read from `counts.conflicted > 0` directly — there is no `conflicted` risk flag.
- `repo_missing`/`not_git_repo` are terminal states (no other flag can co-occur), so their scores are exact.
- Flags not listed above (`staged_changes`, `dependency_file_changed`, `ci_file_changed`, `notebook_changed`, `detached_head`) contribute 0 points.

## Notable files

Rules:

1. Paths are relative to the repo root.
2. The list is capped by `defaults.max_files_per_repo`.
3. Secret-like paths must be redacted.
4. File contents are never read.
5. `include_untracked` affects notable file listing, not raw counts.

## Handoff schema (`repoops.handoff.v1`)

`repoops checkpoint` writes `.repoops/handoff.json` (this schema) and
`.repoops/HANDOFF.md` (a rendering of it) at the repository root. This schema is
independent of `repoops.snapshot.v1` above — single-repo, not multi-repo, and
covers a different set of facts (diff stats, recent commits, an editable
semantic/next-action section).

```json
{
  "schema_version": "repoops.handoff.v1",
  "created_at": "2026-08-01T09:00:00-04:00",
  "repository": {
    "name": "repoops-handoff",
    "root": "/home/fabian/repoops-handoff",
    "branch": "main",
    "detached_head": false,
    "head_short": "a1b2c3d",
    "head_full": "a1b2c3d4e5f6...",
    "upstream": "origin/main",
    "ahead": 0,
    "behind": 0,
    "dirty": true
  },
  "changes": {
    "counts": {
      "modified": 1,
      "staged": 0,
      "untracked": 1,
      "deleted": 0,
      "renamed": 0,
      "conflicted": 0
    },
    "notable_paths": ["src/repoops/handoff.py"],
    "diff_stat": " src/repoops/handoff.py | 4 ++--\n 1 file changed, 2 insertions(+), 2 deletions(-)",
    "cached_diff_stat": ""
  },
  "recent_commits": [
    { "short_hash": "a1b2c3d", "date": "2026-08-01T08:55:00-04:00", "subject": "wip" }
  ],
  "semantic": {
    "goal": "TODO: describe the current goal",
    "current_scope": "TODO: describe what is in scope for this session",
    "out_of_scope": [],
    "completed": [],
    "decisions": [],
    "failed_attempts": [],
    "verification_passed": [],
    "verification_pending": []
  },
  "next_action": {
    "task": "TODO: define the single next concrete task",
    "command": null,
    "success_condition": "TODO: define one concrete, checkable success condition",
    "blocker": null
  }
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | string | Must equal `repoops.handoff.v1`. Any other value (or a missing key) is treated by `repoops resume` as an unsupported schema version — a distinct `BLOCKING` condition from a generic validation failure. |
| `created_at` | string | ISO-8601 with local timezone if available. |
| `repository` | object | See below. |
| `changes` | object | See below. |
| `recent_commits` | array | Up to 5 most recent commits (`git log -5`), each `{short_hash, date, subject}`. Bounded by a fixed limit, not configurable in P0. |
| `semantic` | object | Human/agent-editable. Every `checkpoint` run overwrites this with fresh `TODO:` placeholders — `repoops` never infers or carries forward project intent. Edit the file after checkpointing if you want it to say something else. |
| `next_action` | object | Human/agent-editable, same placeholder rule as `semantic`. |

### `repository`

| Field | Type | Notes |
| --- | --- | --- |
| `name` | string | Repository directory name (`root`'s basename). |
| `root` | string | Absolute path, resolved via `git rev-parse --show-toplevel`. |
| `branch` | string/null | Current branch name, or `null` when `detached_head` is `true`. |
| `detached_head` | bool | Whether HEAD is detached. |
| `head_short` / `head_full` | string | Short and full commit hashes. |
| `upstream` | string/null | e.g. `origin/main`, or `null` when no upstream is configured. |
| `ahead` / `behind` | int/null | Computed from local refs only (`git rev-list --count`) — `repoops checkpoint`/`resume` never run `git fetch`, so these can be stale relative to the actual remote. `null` when there is no upstream. |
| `dirty` | bool | Whether porcelain status has entries (excluding `.repoops/` itself — see below). |

### `changes`

| Field | Type | Notes |
| --- | --- | --- |
| `counts` | object | Same shape as the snapshot schema's `counts` (`staged`, `modified`, `untracked`, `deleted`, `renamed`, `conflicted`). |
| `notable_paths` | array[string] | Redacted, relative changed paths, capped at 30. |
| `diff_stat` | string | Output of `git diff --stat` — filenames and line-change counts only, never full diffs or file contents. Secret-like filenames are redacted the same way as `notable_paths`. |
| `cached_diff_stat` | string | Output of `git diff --cached --stat`, same redaction. |

**`.repoops/` is excluded from all of the above.** Writing a checkpoint creates
`.repoops/handoff.json` and `.repoops/HANDOFF.md`, which would otherwise appear
as a new untracked entry on the very next scan. Since that is a side effect of
running the tool, not of the tracked work, `repoops.handoff` filters `.repoops/`
paths out of `git status`/`git diff --stat` output before computing counts,
`dirty`, `notable_paths`, and the diff-stat strings.

### Handoff-specific allowed Git commands

`repoops checkpoint`/`repoops resume` reuse `git_scan.py`'s `_run_git` whitelist
enforcement (see `docs/SAFETY_CONTRACT.md`) and add five read-only, metadata/stat-only
commands on top of the existing v1 list:

```text
git rev-parse --show-toplevel
git rev-parse HEAD
git diff --stat
git diff --cached --stat
git log -5 --pretty=format:%h<US>%ad<US>%s --date=iso-strict
```

(`<US>` is the ASCII unit-separator `\x1f`, used as a field delimiter so commit
subjects containing arbitrary characters parse unambiguously.) Ahead/behind and
upstream reuse the existing `@{u}`-based commands already whitelisted for
`repoops scan`/`repoops run`. `repoops checkpoint`/`repoops resume` never call
`git fetch` — ahead/behind are always computed from local refs only.

### Resume drift severities

`repoops resume` compares the recorded `repository`/`changes` against a fresh
collection of the same facts and reports each difference as a `DriftItem` with a
severity:

| Drift | Severity |
| --- | --- |
| No checkpoint found at `.repoops/handoff.json` | `BLOCKING` |
| `handoff.json` is not valid JSON | `BLOCKING` |
| `schema_version` does not equal `repoops.handoff.v1` | `BLOCKING` |
| `handoff.json` is valid JSON but fails schema validation | `BLOCKING` |
| `repository.root` does not match the recorded checkpoint | `BLOCKING` |
| `repository.branch` changed | `BLOCKING` |
| `repository.detached_head` changed | `WARNING` |
| `repository.head_full` changed (HEAD moved) | `WARNING` |
| `repository.dirty` or any `changes.counts` field changed | `WARNING` |
| Nothing changed | `NONE` |

The overall severity is the highest severity among all detected drift items
(`BLOCKING` > `WARNING` > `NONE`). `repoops resume` exits `1` when the overall
severity is `BLOCKING`, `0` otherwise. It never asserts that continuing from the
recorded checkpoint is safe when the overall severity is `WARNING` or `BLOCKING`.

## Worklog evidence store

`repoops.worklog` persists scan results to a local SQLite database at `defaults.worklog_db` (see `examples/repos.yaml`). Its purpose is narrow: turn repeated `repoops worklog-scan` runs into low-confidence evidence that a human can review before entering hours anywhere — it is not a timesheet, invoice, or payroll generator (see `docs/SAFETY_CONTRACT.md`).

### `snapshots` table (rows written by `repoops worklog-scan`)

One row per existing, in-git-repo entry in a scan, unconditionally (dirty or clean):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer | Autoincrement primary key. |
| `observed_at` | text | Snapshot timestamp, same ISO-8601 string as the JSON snapshot's `timestamp`. |
| `machine` | text | From config `machine.name`. |
| `project` | text | `repos[].project` from config, or `unassigned` if not set. |
| `repo` | text | Repo name from config. |
| `path` | text | Expanded absolute repo path. |
| `branch` | text/null | Current branch or `HEAD` when detached. |
| `head` | text/null | Short commit hash. |
| `dirty` | integer (0/1) | Whether porcelain status had entries. |
| `staged_count`, `modified_count`, `untracked_count`, `deleted_count`, `renamed_count`, `conflicted_count` | integer | Same counts as the JSON snapshot's `counts`. |
| `ahead`, `behind` | integer/null | Same as the JSON snapshot's `remote.ahead`/`remote.behind`. |
| `risk_flags` | text | JSON-encoded array, same allowed values as the JSON snapshot's `risk_flags`. |
| `changed_paths_redacted` | text | JSON-encoded array of already-redacted `notable_files` paths — never raw file contents or full diffs. |
| `changed_paths_hash` | text | SHA-256 of the sorted, joined redacted path list. Used to detect a repo showing the *same* redacted diff across multiple days; never derived from file contents. |

### Candidate rows (computed on demand by `worklog-weekly` / `worklog-export`, never stored)

`compute_candidates` groups `dirty = 1` snapshot rows by `(day, project)` within a requested date range and derives one `WorklogCandidate` per group:

| Field | Type | Notes |
| --- | --- | --- |
| `date` | string | `YYYY-MM-DD`. |
| `project` | string | Matches the `snapshots.project` column. |
| `repos_touched` | array[string] | Sorted, deduplicated repo names dirty that day for that project. |
| `evidence_summary` | string | Human-readable count of snapshots/repos and any risk flags seen. |
| `real_hours_estimate_range` | string | Wide, conservative range (e.g. `"1-3"`), never a single precise value. |
| `suggested_reportable_hours` | float | Capped at `MAX_DAILY_HOURS` (4.0), regardless of snapshot count. |
| `confidence` | string | `low` (1 snapshot), `medium` (2–3), or `high` (4+) — a function of snapshot count only. |
| `needs_review` | bool | `true` if any repo in the group shows the same `changed_paths_hash` dirty on 3+ distinct days in the queried window (`STALE_STREAK_DAYS`). |

**Candidate rows are evidence only — never approved hours.** No candidate is written back to the SQLite store; `worklog-weekly` prints them and `worklog-export` writes them to CSV, but neither mutates `snapshots`.

### CSV export columns (`repoops worklog-export --format csv`)

Written to `defaults.report_dir/repoops-worklog-<month>.csv`, one row per candidate, in this column order:

```text
date,project,repos_touched,evidence_summary,real_hours_estimate_range,suggested_reportable_hours,confidence,needs_review
```

`repos_touched` is semicolon-joined (`"; "`) since it can contain multiple repo names.
