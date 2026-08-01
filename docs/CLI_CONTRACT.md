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
```

Behavior:

- `PATH` defaults to the current directory;
- discovers the Git repository root from `PATH` (works from any subdirectory);
- collects deterministic, read-only Git facts (branch, HEAD, upstream/ahead/behind
  from local refs only, porcelain status counts, a bounded list of notable changed
  paths, `git diff --stat`, `git diff --cached --stat`, and up to 5 recent commits);
- writes `.repoops/handoff.json` and `.repoops/HANDOFF.md` at the repository root,
  atomically;
- the only files this command ever writes are those two — it never runs `git pull`,
  `git push`, `git reset`, `git clean`, `git fetch`, or any other mutating or
  network-touching Git command, and never invokes an LLM;
- every checkpoint's `semantic` section (goal, scope, decisions, ...) is written
  with explicit `TODO:` placeholders — `repoops` never invents project intent;
- prints the two written paths and exits `0`.

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
| Repository root does not match the recorded checkpoint | `BLOCKING` |
| Branch changed | `BLOCKING` |
| Detached-HEAD state changed | `WARNING` |
| HEAD changed on the same branch | `WARNING` |
| Worktree state changed (dirty flag or any count) | `WARNING` |
| Nothing changed | `NONE` |

Exit code is `1` if the overall severity is `BLOCKING`, otherwise `0`.

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
