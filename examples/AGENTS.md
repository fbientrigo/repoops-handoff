# Coding-agent handoff with RepoOps

Use RepoOps to avoid rediscovering repository state between coding sessions.

## At the start of a session

If `.repoops/handoff.json` exists:

1. Run `repoops resume .`.
2. If RepoOps reports **BLOCKING** drift, stop and report the mismatch before editing code.
3. Read `.repoops/HANDOFF.md` for the recorded goal, decisions, verification, and next action.
4. Treat current repository evidence as authoritative when it conflicts with prose.

If no checkpoint exists, continue normally. A checkpoint will be created before handoff.

## Before ending or handing off

1. Run `repoops checkpoint .`.
2. Edit only the human/agent fields in `.repoops/handoff.json`:
   - `semantic.goal`
   - `semantic.current_scope`
   - decisions / blockers / verification fields when relevant
   - `next_action.task`
   - `next_action.success_condition`
3. Keep the notes factual and concise. Do not infer tests or decisions that did not happen.
4. Run `repoops checkpoint .` again. RepoOps preserves the semantic fields while refreshing Git facts and regenerating `.repoops/HANDOFF.md`.
5. Never hand-edit `.repoops/HANDOFF.md`; it is generated output.

The next session should be able to answer three questions immediately: what was being done, what evidence exists, and what single action comes next.
