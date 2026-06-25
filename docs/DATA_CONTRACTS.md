# Data contracts — repoops v0

## Snapshot schema

```json
{
  "schema_version": "repoops.snapshot.v0",
  "machine": "nasapcdeb",
  "timestamp": "2026-06-25T09:00:00-04:00",
  "repos": []
}
```

Required fields:

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | string | Must equal `repoops.snapshot.v0`. |
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
| `risk_flags` | array[string] | Known v0 flags only. |

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

Allowed v0 flags:

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
```

No other risk flags should be emitted in v0 unless the schema version changes.

## Notable files

Rules:

1. Paths are relative to the repo root.
2. The list is capped by `defaults.max_files_per_repo`.
3. Secret-like paths must be redacted.
4. File contents are never read.
5. `include_untracked` affects notable file listing, not raw counts.
