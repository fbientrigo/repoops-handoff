# Development workflow

## 1. Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 2. Run tests by layer

```bash
pytest tests/test_config.py
pytest tests/test_git_scan.py
pytest tests/test_report.py
pytest tests/test_notify.py
```

## 3. Run full local gate

```bash
ruff check .
pytest
```

## 4. Implementation order

Recommended order:

1. config loading;
2. path expansion;
3. porcelain parser;
4. risk flags;
5. repo scanner;
6. Markdown report;
7. CLI scan/run;
8. notification disabled/no-op;
9. Telegram/Slack/SMTP backends.

## 5. Manual smoke test

```bash
repoops scan --config examples/repos.yaml
repoops run --config examples/repos.yaml
repoops notify --config examples/repos.yaml --report ~/.local/share/repoops/reports/<report>.md
```

## 6. Safety check before merging

Search for forbidden commands:

```bash
rg "git (pull|push|reset|clean|checkout|switch|add|commit|stash)" src tests docs
```

Expected result: no forbidden implementation command usage.
