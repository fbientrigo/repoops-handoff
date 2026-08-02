# Security Policy

`repoops-handoff` takes security and local data privacy seriously. This document details our security practices, design guarantees, and how to report vulnerabilities.

---

## Safety & Privacy Guarantees

### 1. Secret Redaction & Path Inspection

`repoops` scans file paths and status codes returned by `git status --porcelain=v2`. It never reads or transmits file contents.

Paths matching secret-like patterns (e.g. `.env`, `id_rsa`, `*.pem`, `*.key`, `credentials.json`, `config.secret.yaml`) are flagged with the `possible_secret_file` risk flag and redacted in generated reports and notification payloads to prevent accidental disclosure.

### 2. No File Content Collection

Scanning and handoff workflows collect only high-level structural metadata:
* Branch name and short commit hash;
* Modified/staged/untracked file counts;
* `git diff --stat` change line counters;
* Commit message summaries (up to 5 recent commits).

Source code, file diffs, and file contents are never read, stored, or transmitted by `repoops`.

### 3. Strictly Read-Only Operations

`repoops` operates under a zero-mutation guarantee:
* No mutating Git commands are ever executed (`git pull`, `git push`, `git reset`, `git checkout`, `git switch`, `git clean`).
* Checkpoint creation (`repoops checkpoint`) only writes inside `.repoops/` within the target repository (`.repoops/handoff.json` and `.repoops/HANDOFF.md`). No existing repository files are modified.
* Network access is strictly restricted to:
  1. `git fetch --prune` when explicitly requested via `--fetch` or `defaults.fetch: true`.
  2. Telegram HTTP API calls when `notifications.enabled: true` and `notifications.channel: telegram` are explicitly configured.

---

## Reporting a Vulnerability

If you discover a security vulnerability or secret leakage issue in `repoops-handoff`, please do **NOT** open a public GitHub issue.

Instead, please report it responsibly by contacting the maintainer:

* **Email**: `42480199+fbientrigo@users.noreply.github.com`
* **Subject**: `[SECURITY] Vulnerability Report - repoops-handoff`

Please include:
1. Description of the vulnerability or security concern;
2. Steps or proof-of-concept to reproduce the issue;
3. Impact assessment.

You will receive an acknowledgment within 48 hours, and we will work to address and publish a patch in a timely manner.
