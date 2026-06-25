# CLI contract — repoops v0

## `repoops scan`

```bash
repoops scan --config examples/repos.yaml
```

Behavior:

- reads config;
- scans repositories;
- prints Rich summary table;
- does not write files;
- does not notify;
- returns exit code `0` if config and scan complete.

## `repoops run`

```bash
repoops run --config examples/repos.yaml
```

Behavior:

- reads config;
- scans repositories;
- prints Rich summary table;
- writes JSON snapshot;
- writes Markdown report;
- notifies only if enabled;
- prints generated artifact paths.

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
