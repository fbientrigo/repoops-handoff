# Development workflow

## 1. Install

```bash
python -m venv .venv
source .venv/bin/activate  # Or .venv\Scripts\Activate.ps1 on Windows
pip install -e ".[dev]"
```

## 2. Run tests by layer

```bash
pytest tests/test_config.py
pytest tests/test_git_scan.py
pytest tests/test_report.py
pytest tests/test_notify.py
pytest tests/test_handoff.py
```

## 3. Complete local quality gate

Before opening a PR or tagging a release, run all steps of the local quality gate:

```bash
# 1. Linting
ruff check .

# 2. Formatting check
ruff format --check .

# 3. Test suite
pytest

# 4. Build distribution packages (sdist + wheel)
python -m build

# 5. Check distribution metadata
python -m twine check dist/*
```

## 4. Implementation order

Recommended order:

1. config loading;
2. path expansion;
3. porcelain parser;
4. risk flags;
5. repo scanner;
6. Markdown report;
7. CLI scan/run/notify/checkpoint/resume;
8. worklog scan/weekly/export;
9. Telegram backend.

## 5. Manual smoke test

```bash
repoops scan
repoops scan --project thesis
repoops scan --tag ship
repoops run --config examples/repos.yaml
repoops notify --config examples/repos.yaml --report ~/.local/share/repoops/reports/<report>.md
repoops checkpoint .
repoops resume .
```

## 6. Safety check before merging

Search for forbidden commands:

```bash
rg "git (pull|push|reset|clean|checkout|switch|add|commit|stash)" src tests docs
```

Expected result: no forbidden implementation command usage.
