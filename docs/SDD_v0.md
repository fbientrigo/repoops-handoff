# Software Design Document — repoops v0 Skateboard

## 1. Goals

v0 provides a small but useful local workflow:

1. Load a YAML config listing repositories.
2. Scan each repository without mutating it.
3. Detect dirty worktrees using `git status --porcelain=v1`.
4. Summarize branch, short HEAD, counts, notable files, and risk flags.
5. Generate JSON and Markdown artifacts.
6. Print a concise Rich terminal table.
7. Support notification disabled/no-op mode.

## 2. Non-goals

v0 does not:

- pull, push, reset, clean, checkout, switch, add, commit, or stash;
- run tests inside target repositories;
- inspect CI remotely;
- invoke coding agents;
- read changed file contents;
- emit diffs;
- expose secret values;
- use a database;
- run as a daemon;
- provide a web UI.

## 3. Module boundaries

| Module | Responsibility |
| --- | --- |
| `repoops.config` | Load and validate YAML config with Pydantic. |
| `repoops.paths` | Expand `~`, normalize paths, ensure output directories. |
| `repoops.git_scan` | Read-only Git scanning, porcelain parsing, risk classification. |
| `repoops.report` | Markdown and Rich terminal output. |
| `repoops.notify` | Notification no-op mode and future channel boundary. |
| `repoops.cli` | Typer command orchestration. |

## 4. Data model

The root artifact is a snapshot:

```json
{
  "schema_version": "repoops.snapshot.v0",
  "machine": "nasapcdeb",
  "timestamp": "2026-06-25T09:00:00-04:00",
  "repos": []
}
```

Each repo entry records only metadata:

```json
{
  "name": "dihiggs",
  "path": "/home/fabian/dihiggs",
  "exists": true,
  "is_git_repo": true,
  "branch": "main",
  "head": "a1b2c3d",
  "dirty": true,
  "counts": {
    "modified": 3,
    "staged": 0,
    "untracked": 2,
    "deleted": 0,
    "renamed": 0,
    "conflicted": 0
  },
  "notable_files": ["src/model.py", "tests/test_model.py"],
  "risk_flags": ["dirty", "untracked_files"]
}
```

## 5. CLI contract

```bash
repoops scan --config examples/repos.yaml
repoops run --config examples/repos.yaml
repoops notify --config examples/repos.yaml --report path/to/report.md
```

`scan` prints terminal output only.

`run` writes JSON and Markdown and may notify.

`notify` sends an existing report or exits as no-op when disabled.

## 6. Safety contract

The scanner only runs these Git commands:

```text
git rev-parse --is-inside-work-tree
git rev-parse --abbrev-ref HEAD
git rev-parse --short HEAD
git status --porcelain=v1
```

No file contents are read from target repositories.
Secret-like paths are redacted before rendering or notification.

## 7. Test strategy

The tests are organized around the v0 contract:

- config loading;
- missing repo scan;
- non-Git directory scan;
- clean Git repo scan;
- dirty Git repo scan;
- porcelain parsing;
- risk flag classification;
- Markdown report rendering;
- notification disabled/no-op behavior.

Temporary Git repositories are created only inside pytest `tmp_path`.

## 8. CI strategy

GitHub Actions runs:

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

No external secrets or network services are required for CI.
