# RepoOps session protocol

Use RepoOps as the repository-state handoff layer between Claude sessions or between Claude and another coding agent.

## Session start

When `.repoops/handoff.json` exists:

- run `repoops resume .` before making changes;
- if the result contains **BLOCKING** drift, report it and do not continue silently;
- read `.repoops/HANDOFF.md` to recover the prior goal, decisions, verification evidence, and next action;
- prefer observed repository state over stale prose.

## Session end / agent handoff

- run `repoops checkpoint .`;
- update only semantic and next-action fields in `.repoops/handoff.json` with facts from this session;
- record verification only when it was actually executed;
- define one concrete next task and one checkable success condition;
- run `repoops checkpoint .` again to refresh Git facts and regenerate `.repoops/HANDOFF.md`;
- do not edit `.repoops/HANDOFF.md` directly.

Keep the handoff short enough that the next agent can resume without re-auditing the whole repository.
