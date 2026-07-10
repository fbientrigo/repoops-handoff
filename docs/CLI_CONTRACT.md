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
