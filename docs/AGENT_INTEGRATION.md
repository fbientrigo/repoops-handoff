# Agent integration

RepoOps works best when the coding agent owns the handoff bookkeeping instead of asking the developer to reconstruct context manually.

Copy the appropriate example into a repository:

```bash
cp examples/AGENTS.md /path/to/project/AGENTS.md
# or
cp examples/CLAUDE.md /path/to/project/CLAUDE.md
```

Both templates implement the same small protocol:

```text
session starts
    |
    v
repoops resume .
    |
    +-- BLOCKING --> stop and surface drift
    |
    v
read HANDOFF.md -> work
    |
    v
repoops checkpoint .
    |
    v
update semantic + next_action in handoff.json
    |
    v
repoops checkpoint . -> generated HANDOFF.md
```

The templates intentionally do not ask agents to checkpoint every edit. RepoOps is a session-boundary tool, not another workflow to babysit.
