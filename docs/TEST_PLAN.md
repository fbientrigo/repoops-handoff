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
- `channel: telegram` with both env vars set sends a synthesis derived from the report and returns `sent`.
- `channel: telegram` with a missing env var raises `ValueError` naming the missing variable.
- A Telegram send failure is non-fatal: returns `skipped` with a sanitized reason, never raises.
- Synthesis keeps header/Summary/Attention summary, drops the per-repo `## Repositories` section, and truncates to the configured limit.

## Telegram transport tests

- A successful call posts JSON `{chat_id, text, disable_web_page_preview}` to `https://api.telegram.org/bot<token>/sendMessage`.
- An `HTTPError` raises `TelegramError` containing only the HTTP status code — never the bot token or URL.
- A `URLError` raises `TelegramError` containing only the sanitized connection reason — never the bot token or URL.
- A non-200 status without an exception still raises `TelegramError`.

## Handoff tests (`repoops checkpoint` / `repoops resume`)

- `checkpoint` creates `.repoops/handoff.json` + `HANDOFF.md` in a clean repository; recorded `dirty=False`, all counts `0`.
- `checkpoint` in a dirty repository records correct `modified`/`untracked` counts and a non-empty `diff_stat`.
- `checkpoint` records staged and untracked changes distinctly (`counts.staged`, `counts.untracked`, `cached_diff_stat`).
- `checkpoint` in a detached-HEAD repo records `detached_head=True`, `branch=None`.
- `checkpoint` discovers the repository root correctly when run from a subdirectory.
- `checkpoint` redacts secret-like paths in `notable_paths`, `diff_stat`, and the rendered Markdown — never leaks matched content (e.g. `.env` contents, `credentials` in a filename).
- Writing a checkpoint never shows up as drift on the immediately following `resume` (`.repoops/` is excluded from collected facts).
- `resume` immediately after `checkpoint` reports overall severity `NONE`, exit code `0`.
- `resume` after a branch change reports a `BLOCKING` `branch` drift item with exact old/new values.
- `resume` after a same-branch commit reports a `WARNING` (not `BLOCKING`) `head` drift item.
- `resume` when only the dirty/untracked count changed reports `WARNING`, not `BLOCKING`.
- `resume` with invalid JSON in `handoff.json` reports `BLOCKING` with no traceback leaked to the user.
- `resume` with an unsupported `schema_version` reports a distinct `BLOCKING` message naming the version, separate from a generic validation failure.
- `resume` with a well-formed but shape-invalid `handoff.json` (missing required fields) reports `BLOCKING`.
- `resume` against a repository whose recorded `repository.root` doesn't match the current root (simulating a moved/renamed clone) reports `BLOCKING` with exact old/new paths.
- `resume` with no checkpoint at all reports `BLOCKING` and suggests running `repoops checkpoint .`.
- CLI exit code is `1` for any `BLOCKING` overall severity, `0` otherwise (`NONE`/`WARNING`).
- `repoops scan`/`run`/`worklog-scan` are unaffected by `repoops.handoff` (regression coverage for unrelated existing functionality).
- `HANDOFF.md` states near the top that `handoff.json` is canonical and that manual Markdown edits are not consumed by `resume`.
- `HANDOFF.md` renders the actual content of decisions, failed attempts, and verification entries — never reduces them to bare counts.
- `resume` output includes the actual decisions, failed attempts, passed/pending verification, and the exact success condition — not just goal and a completed-count.

## Semantic preservation tests (`repoops checkpoint`, P0 hardening)

- A second `checkpoint` on the same repository preserves every edited `semantic` field and every `next_action` field verbatim.
- A second `checkpoint` still refreshes deterministic Git facts (branch, HEAD, worktree, remote, diff stats, recent commits) and the timestamp.
- The regenerated `HANDOFF.md` after a second `checkpoint` contains the preserved actual semantic values, not `TODO:` placeholders.
- `resume` after a second `checkpoint` surfaces the preserved semantic values in its output.
- `checkpoint --reset-semantic` replaces existing semantic/next-action content with `TODO:` placeholders.
- `checkpoint` without `--reset-semantic` never resets semantic content on its own.
- `checkpoint` fails non-zero, with an explanatory message, when the existing `handoff.json` is invalid JSON, has an unsupported schema, or is structurally invalid — and leaves both `handoff.json` and `HANDOFF.md` byte-for-byte unchanged.
- `checkpoint --reset-semantic` recovers from an existing invalid/unusable `handoff.json`.
- `checkpoint` fails non-zero when the existing `handoff.json` is identifiable as belonging to a different repository (different root, no matching remote identity), and leaves both files unchanged.

## Repository relocation tests (`repoops resume`, P0 hardening)

- `normalize_remote_identity` maps `git@host:owner/repo.git`, `https://host/owner/repo.git`, and `ssh://git@host/owner/repo.git` (with/without `.git`, trailing slash, port) to the same identity.
- `normalize_remote_identity` returns different identities for a different owner or host.
- `normalize_remote_identity` returns `None` for empty input or an unparseable local path.
- `normalize_remote_identity` never returns embedded HTTPS credentials, tokens, or query-string values — verified with a URL containing an embedded token.
- Same repository root, same remote: no relocation drift, overall severity `NONE`.
- Different root, same normalized remote identity (SSH vs. HTTPS forms of the same repo): `WARNING` (`repository_relocated`), exit code `0`.
- Different root, different normalized remote identity: `BLOCKING`, exit code `1`.
- Different root, remote identity unavailable on one or both sides: `BLOCKING`, exit code `1`.
- Remote identity changed at the same root (both sides known and different): `BLOCKING`.
- No secret substring (embedded credential/token) appears in `handoff.json`, `HANDOFF.md`, `resume` output, or `checkpoint` output for a repository with a credential-embedded remote URL.
