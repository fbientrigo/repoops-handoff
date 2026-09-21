# repoops-handoff

**Carry the Git state, decisions, and next action from one coding-agent session to the next.**

RepoOps is a small local CLI for the moment when a Codex, Claude Code, Aider, OpenHands, or human session ends and somebody else has to continue.

Instead of asking the next agent to rediscover the repository, RepoOps writes a deterministic checkpoint and verifies that the repository still matches before work resumes.

```text
working session
      |
      v
repoops checkpoint .
      |
      v
.repoops/handoff.json  -> canonical checkpoint
.repoops/HANDOFF.md     -> readable handoff
      |
      | new session / new agent / new machine
      v
repoops resume .
      |
      +-- NONE/WARNING -> continue with context
      |
      +-- BLOCKING ----> stop: repository drifted
```

## See the idea in 10 seconds

```bash
pipx install repoops-handoff
repoops demo
```

`repoops demo` is zero-config and read-only. It only shows the checkpoint/resume workflow; it does not touch Git or create files.

Example:

```text
$ repoops checkpoint .
Checkpoint written: .repoops/handoff.json
Handoff markdown: .repoops/HANDOFF.md

# New agent or new session
$ repoops resume .
RepoOps resume
Overall drift: NONE
Branch: main
HEAD: matches checkpoint
Worktree: matches checkpoint
Next action: run the failing unit test and fix only that path
```

## The two commands that matter

At the end of a useful session:

```bash
repoops checkpoint .
```

RepoOps records deterministic repository evidence such as branch, HEAD, worktree state, diff statistics, recent commits, and normalized remote identity.

It writes:

- `.repoops/handoff.json` — canonical source of truth;
- `.repoops/HANDOFF.md` — generated Markdown for the next human or agent.

At the beginning of the next session:

```bash
repoops resume .
```

RepoOps compares the live repository against the checkpoint:

- **NONE** — recorded Git state still matches;
- **WARNING** — explainable non-fatal drift;
- **BLOCKING** — branch/repository/state mismatch that should be resolved before continuing.

This is deliberately not an AI memory system. RepoOps stores explicit repository evidence and explicit human/agent notes; it does not silently infer what happened.

## Make the agent do the bookkeeping

If you use an agent instruction file, copy one of the included protocols:

```bash
cp examples/AGENTS.md /path/to/project/AGENTS.md
# or
cp examples/CLAUDE.md /path/to/project/CLAUDE.md
```

The protocol tells the agent to:

1. run `repoops resume .` when a checkpoint exists;
2. stop and surface BLOCKING drift instead of silently continuing;
3. read `.repoops/HANDOFF.md`;
4. work normally;
5. checkpoint at handoff time;
6. record only factual semantic notes and one concrete next action;
7. regenerate the handoff for the next session.

The intent is less babysitting, not another process to maintain. See [Agent integration](docs/AGENT_INTEGRATION.md).

## Why not just write a handoff note?

A Markdown note can say "tests passed on branch X" long after the branch, HEAD, or worktree has changed.

RepoOps separates:

```text
deterministic evidence              semantic context
----------------------              ----------------
branch / HEAD                       goal
dirty counts                        scope
notable paths                       decisions
diff statistics                     blockers
recent commits                      verification notes
remote identity                     one next action
```

Repeated checkpoints refresh the Git facts while preserving the semantic fields. `HANDOFF.md` is generated output and should not be edited by hand.

## Safety contract

The normal RepoOps handoff workflow is intentionally conservative:

- no `git pull`, `push`, `reset`, `checkout`, `switch`, or `clean`;
- checkpoint scanning does not harvest source-file contents or full diffs;
- secret-looking paths are redacted;
- raw remote URLs are never stored;
- `resume` is read-only;
- `repoops demo` performs no Git commands and writes nothing.

See [Safety contract](docs/SAFETY_CONTRACT.md) for the full guarantees.

## Multi-repository status is still included

RepoOps also answers "which repository needs attention?" across many local repositories.

Create `~/.config/repoops/repos.yaml`:

```yaml
machine:
  name: dev-laptop

repos:
  - name: thesis-core
    path: ~/code/thesis-core
    project: thesis
    tags: [physics, ml]

  - name: firmware
    path: ~/code/firmware
    project: lab
    tags: [fpga]
```

Then:

```bash
repoops scan
repoops scan --project thesis
repoops scan --tag fpga
```

Configuration resolution is:

1. `--config PATH`;
2. `REPOOPS_CONFIG`;
3. `~/.config/repoops/repos.yaml`.

## Other included commands

These remain available but are not required for agent handoffs:

| Command | Purpose |
| --- | --- |
| `repoops run` | scan repos and write JSON + Markdown status reports |
| `repoops notify` | deliver a generated report through configured notifications |
| `repoops worklog-scan` | record conservative local worklog evidence |
| `repoops worklog-weekly` | inspect weekly worklog candidates |
| `repoops worklog-export` | export monthly candidate rows as CSV |

For exact CLI behavior see [CLI contract](docs/CLI_CONTRACT.md).

## Installation

Recommended:

```bash
pipx install repoops-handoff
```

For development:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

ruff check .
ruff format --check .
pytest
python -m build
python -m twine check dist/*
```

## Design boundaries

RepoOps intentionally does **not**:

- infer repository truth with an LLM;
- auto-commit or auto-push;
- modify your working tree to "fix" drift;
- require a hosted service;
- require configuration for `checkpoint`, `resume`, or `demo`;
- checkpoint every edit.

The useful boundary is the session handoff.

## Documentation

- [Agent integration](docs/AGENT_INTEGRATION.md)
- [CLI contract](docs/CLI_CONTRACT.md)
- [Safety contract](docs/SAFETY_CONTRACT.md)
- [Data contracts](docs/DATA_CONTRACTS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Development](docs/DEVELOPMENT.md)

## License

MIT.
