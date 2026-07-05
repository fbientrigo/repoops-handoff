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
