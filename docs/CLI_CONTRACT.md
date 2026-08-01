# CLI contract — repoops v1

## `repoops scan`

```bash
repoops scan --config examples/repos.yaml
repoops scan --config examples/repos.yaml --fetch
```

Behavior:

- reads config;
- scans repositories;
- prints Rich summary table (now including `Ahead`, `Behind`, `Score` columns);
- does not write files;
- does not notify;
- returns exit code `0` if config and scan complete.
- `--fetch` forces a safe `git fetch --prune` per repo before computing ahead/behind (see "Notes on `--fetch`" below). Never runs `git pull`.

## `repoops run`

```bash
repoops run --config examples/repos.yaml
repoops run --config examples/repos.yaml --fetch
```

Behavior:

- reads config;
- scans repositories;
- prints Rich summary table;
- writes JSON snapshot;
- writes Markdown report (now including an "Attention summary" section);
- notifies only if enabled;
- prints generated artifact paths.
- `--fetch` forces a safe `git fetch --prune` per repo before computing ahead/behind, same as `scan --fetch`.

## Notes on `--fetch`

- Resolution is **OR**, not override: `effective_fetch = --fetch OR config.defaults.fetch`. The CLI flag can only force fetch **on**; there is no `--no-fetch` to force it off for a run where the config default is `true`.
- Fetch only runs when `defaults.remote_check` is also enabled — fetching is meaningless if ahead/behind isn't being computed.
- Fetch is bounded by `defaults.fetch_timeout_seconds` and never blocks on interactive credential prompts (`GIT_TERMINAL_PROMPT=0`).
- A fetch failure on one repo (bad remote, network unreachable, timeout) never aborts the scan — it's recorded as `fetch_error` on that repo and the run continues.
- `git fetch --prune` only updates local remote-tracking refs (e.g. `origin/main`). It never touches the working tree and is never `git pull`.

## `repoops notify`

```bash
repoops notify --config examples/repos.yaml --report path/to/report.md
```

Behavior:

- reads config;
- validates report path exists;
- sends or no-ops depending on config;
- does not scan repositories;
- does not generate new artifacts.

`channel: telegram` sends a short synthesis of the report (see `docs/SAFETY_CONTRACT.md` → "Telegram backend"). It requires `REPOOPS_TELEGRAM_BOT_TOKEN` and `REPOOPS_TELEGRAM_CHAT_ID` in the environment; missing variables raise immediately, while a failed API call is reported as `skipped` rather than raised. `slack` and `email` remain `NotImplementedError` stubs.

## `repoops checkpoint [PATH]`

```bash
repoops checkpoint .
repoops checkpoint /path/to/repo
repoops checkpoint . --reset-semantic
```

`.repoops/handoff.json` is the **canonical, editable** handoff. `.repoops/HANDOFF.md`
is a deterministic, generated rendering of it — never hand-edit the Markdown; edits
there are not read back by `repoops resume` or the next `repoops checkpoint`.

Behavior:

- `PATH` defaults to the current directory;
- discovers the Git repository root from `PATH` (works from any subdirectory);
- collects deterministic, read-only Git facts (branch, HEAD, upstream/ahead/behind
  from local refs only, porcelain status counts, a bounded list of notable changed
  paths, `git diff --stat`, `git diff --cached --stat`, up to 5 recent commits, and a
  normalized Git remote identity — see "Repository relocation" below);
- writes `.repoops/handoff.json` and `.repoops/HANDOFF.md` at the repository root,
  atomically;
- the only files this command ever writes are those two — it never runs `git pull`,
  `git push`, `git reset`, `git clean`, `git fetch`, or any other mutating or
  network-touching Git command, and never invokes an LLM;
- prints the two written paths and exits `0`.

**Semantic preservation (default).** If a valid, same-repository
`.repoops/handoff.json` already exists, its `semantic` section (goal, scope,
decisions, failed attempts, verification, ...) and `next_action` are carried
forward unchanged; only the deterministic Git facts above and `created_at` are
refreshed. If no prior checkpoint exists, `semantic`/`next_action` start as
explicit `TODO:` placeholders — `repoops` never invents project intent.

**`--reset-semantic`.** Discards any existing `semantic`/`next_action` content —
including content from an existing file that could not otherwise be safely
preserved — and replaces it with the same `TODO:` placeholders used for a first
checkpoint. This is the only way to intentionally discard prior semantic context;
the default command never does so silently.

**Unsafe existing state.** If `.repoops/handoff.json` already exists but is invalid
JSON, has an unsupported `schema_version`, fails schema validation, or is
identifiable as belonging to a different repository (see "Repository relocation"),
the default command fails with a non-zero exit code, explains why preservation is
unsafe, and leaves both existing files untouched. Only `--reset-semantic` may
proceed past this.

`.repoops/` itself is excluded from the collected Git facts (status counts, notable
paths, diff stats) so writing a checkpoint never shows up as drift on the very next
`repoops resume`.

## `repoops resume [PATH]`

```bash
repoops resume .
repoops resume /path/to/repo
```

Behavior:

- `PATH` defaults to the current directory;
- discovers the Git repository root from `PATH`;
- loads and validates `.repoops/handoff.json` (missing file, invalid JSON, and an
  unsupported `schema_version` are each reported as a distinct `BLOCKING` drift
  item, never a raw traceback);
- collects the same deterministic Git facts `checkpoint` collects, for the
  current state;
- compares recorded vs. current state and prints four clearly separated sections
  to stdout: `RECORDED HANDOFF`, `CURRENT REPOSITORY STATE`, `DRIFT DETECTED`,
  `NEXT ACTION`;
- never modifies `.repoops/handoff.json` or `.repoops/HANDOFF.md`;
- never claims it is safe to continue when `WARNING` or `BLOCKING` drift exists.

Drift severities (see `docs/DATA_CONTRACTS.md` for the full table):

| Condition | Severity |
| --- | --- |
| No checkpoint found / invalid JSON / unsupported schema version | `BLOCKING` |
| Same repository root | no relocation drift |
| Different root, same normalized remote identity | `WARNING` (`repository_relocated`) |
| Different root, different normalized remote identity | `BLOCKING` |
| Different root, remote identity unavailable on either side | `BLOCKING` |
| Remote identity changed at the same root, both sides known and different | `BLOCKING` |
| Remote identity changed at the same root, one side unknown | `WARNING` |
| Branch changed | `BLOCKING` |
| Detached-HEAD state changed | `WARNING` |
| HEAD changed on the same branch | `WARNING` |
| Worktree state changed (dirty flag or any count) | `WARNING` |
| Nothing changed | `NONE` |

Exit code is `1` if the overall severity is `BLOCKING`, otherwise `0`.

### Repository relocation

`repoops` is a single-machine, single-checkout tool — it does not synchronize
checkpoints across machines. But a checkpoint file itself is just JSON, and copying
it to a different clone of the *same* repository (a different machine, container, or
path) is a legitimate, expected workflow. To support that without weakening the
"is this really the same repository?" check, each checkpoint also records a
`remote_identity`: `git config --get remote.origin.url`, normalized to a
`host/owner/repo`-shaped string that compares equal across common SSH and HTTPS
remote forms (see `docs/DATA_CONTRACTS.md`). Only this normalized identity is
stored — never the raw remote URL, so embedded credentials, tokens, or query
strings are never written to `handoff.json`, `HANDOFF.md`, or printed anywhere.
The absolute path (`repository.root`) is still recorded as contextual evidence, but
it is no longer the sole basis for the same-repository check.

## `repoops worklog-scan`

```bash
repoops worklog-scan --config examples/repos.yaml
```

Behavior:

- reads config;
- calls the same `build_snapshot` used by `scan`/`run` (no new Git commands, no `--fetch`);
- opens (creating if needed) the SQLite store at `defaults.worklog_db`;
- inserts one snapshot row per existing, in-git-repo entry in the scan;
- does not print a table or write JSON/Markdown artifacts;
- prints the number of rows inserted and the store path.

## `repoops worklog-weekly`

```bash
repoops worklog-weekly --config examples/repos.yaml --week 2026-W28
```

Behavior:

- reads config;
- opens the existing SQLite store (does not scan repositories);
- computes candidate rows for the Monday–Sunday range of the given ISO week (`YYYY-Www`);
- prints a Rich table of candidates to the terminal;
- these rows are evidence for human review, never approved hours (see `docs/DATA_CONTRACTS.md` and `docs/SAFETY_CONTRACT.md`).

## `repoops worklog-export`

```bash
repoops worklog-export --config examples/repos.yaml --month 2026-07 --format csv
```

Behavior:

- reads config;
- opens the existing SQLite store (does not scan repositories);
- computes candidate rows for the given calendar month (`YYYY-MM`);
- writes them to `defaults.report_dir/repoops-worklog-<month>.csv`;
- `--format` only accepts `csv`; any other value raises a `BadParameter` error before the store is opened;
- prints the export path;
- does not generate a payroll or invoice report — the CSV is raw candidate evidence only.
