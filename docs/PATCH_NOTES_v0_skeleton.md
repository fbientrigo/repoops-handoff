# Patch notes — v0 skeleton

This skeleton establishes the v0 contract and a small implementation base.

## Included

- Project packaging with `pyproject.toml`.
- CLI entry point `repoops`.
- YAML config model.
- Snapshot data model.
- Safe read-only Git command wrapper.
- Porcelain parser.
- Risk flag classifier.
- Markdown report renderer.
- Rich terminal table.
- Notification no-op behavior.
- Tests for config, scan, report, and notify.
- GitHub Actions CI.

## Intentionally deferred

- Telegram delivery.
- Slack webhook delivery.
- SMTP delivery.
- Agent handoff generation.
- CI inspection.
- Test execution inside target repos.
- Any repository mutation command.

## Next implementation target

Add actual Telegram/Slack/SMTP backends behind the existing `notify_report` boundary, keeping disabled/no-op behavior as the default safe mode.
