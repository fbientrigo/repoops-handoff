# Test plan — repoops v0

## Config tests

- Load valid config.
- Expand `~` paths.
- Reject missing repo name.
- Accept `notifications.channel: none`.

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

## Report tests

- Markdown contains machine, timestamp, repo name, branch, head, counts, flags.
- Clean repos can be omitted from detailed sections.
- Secret-like paths are redacted.
- File contents are not included.

## Notify tests

- Disabled notification is no-op.
- `channel: none` is no-op.
- Missing report path fails cleanly.
- Secret environment variable values are never logged or returned.
