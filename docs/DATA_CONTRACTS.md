# Data contracts — repoops v1

## Changelog

- **v1**: added `remote` (`RemoteSyncStatus`) and `attention_score` to the repo snapshot; added 5 remote-related risk flags. `schema_version` bumped from `repoops.snapshot.v0` to `repoops.snapshot.v1`.

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
