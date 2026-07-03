# Test plan — repoops v1

## Config tests

- Load valid config.
- Expand `~` paths.
- Reject missing repo name.
- Accept `notifications.channel: none`.
- `defaults.remote_check`/`fetch`/`fetch_timeout_seconds` default to `true`/`false`/`20`.
- `defaults.remote_check`/`fetch`/`fetch_timeout_seconds` can be overridden via YAML.

## Git scan tests

- Missing repo returns `repo_missing`.
- Non-Git directory returns `not_git_repo`.
- Clean Git repo returns no dirty flags.
- Dirty Git repo counts modified and untracked files.
- Porcelain parser handles staged, modified, untracked, deleted, renamed, and conflicted lines.
- Notable files respect `max_files_per_repo`.
- `include_untracked: false` suppresses untracked notable files but not counts.

## Risk flag tests

- `many_changes` when above threshold.
- `possible_secret_file` with redaction.
- `dependency_file_changed` for dependency manifests and lockfiles.
- `ci_file_changed` for workflow files.
- `notebook_changed` for `.ipynb`.
- `detached_head` when branch is `HEAD`.

## Remote sync tests

- Repo with no upstream: `has_upstream=False`, `no_upstream` risk flag.
- Clean repo with upstream: `ahead=0`, `behind=0`, no remote risk flags.
- Repo ahead of upstream: `ahead_remote` flag, correct `ahead` count.
- Repo behind upstream (via a second local clone pushing to a shared bare remote, then `fetch=True`): `behind_remote` flag, correct `behind` count.
- Repo diverged from upstream (ahead and behind both > 0): `ahead_remote`, `behind_remote`, and `diverged_remote` all present.
- `remote_check=False` suppresses all remote fields and flags entirely, even for a repo with no upstream.
- `fetch=False` (the default) makes no network attempt: `fetched=False`, `fetch_error=None`, verified against a repo whose `origin` points at an unreachable path.
- `fetch=True` populates `fetched=True` and refreshes ahead/behind against updated remote-tracking refs.
- A fetch failure on one repo does not crash `build_snapshot` for the others; `fetch_error` is set and `fetch_failed` is added, sanitized (no raw stderr, no credentials, capped length).
- `resolve_fetch` implements OR semantics across all 4 boolean combinations.
- `_run_git` raises on any non-whitelisted git command (regression test for the safety whitelist).

## Attention score tests

- Clean repo (upstream, ahead=0, behind=0, no other flags) scores `0`.
- Each flag in the point table contributes its documented score (dirty, possible_secret_file, etc.).
- `counts.conflicted > 0` contributes `80` even without a dedicated risk flag.
- `repo_missing` and `not_git_repo` score exactly `100`/`90` (terminal states, no other flags present).
- Relative ordering across a mixed snapshot matches the point table (e.g. diverged > dirty > untracked-only).

## Report tests

- Markdown contains machine, timestamp, repo name, branch, head, counts, flags.
- Clean repos can be omitted from detailed sections.
- Secret-like paths are redacted.
- File contents are not included.
- Markdown "Attention summary" is sorted by descending `attention_score` and omits zero-score repos.
- Markdown/Rich never leak raw `fetch_error` detail beyond the already-sanitized string.
- Rich table includes `Ahead`/`Behind`/`Score` columns, `-` for `None` values.

## CLI tests

- `run --fetch` forces a fetch even when `defaults.fetch: false` in config (verified via the written JSON snapshot).
- `scan --fetch` runs without error.

## Notify tests

- Disabled notification is no-op.
- `channel: none` is no-op.
- Missing report path fails cleanly.
- Secret environment variable values are never logged or returned.
