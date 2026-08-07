# `repoops agent-run` — Antigravity CLI integration (P0)

## Scope

This is the smallest integration that lets RepoOps execute **one** externally
supplied task in a local Git repository via the official Antigravity CLI
(`agy`) and produce a deterministic, machine-readable execution record.

It does **not** include a scheduler, task-selection policy, reviewer/architect
agent, GitHub integration, or an autonomous multi-task loop. Those are later
stages.

Validated against a real, locally installed `agy` (version 1.1.10) — not just
mocked fixtures. See "Observed real CLI behavior" below.

## Prerequisites

- Antigravity CLI (`agy`) installed and on `PATH`, version **>= 1.1.10**.
  `repoops agent-run` detects `agy`, parses `agy --version`, and refuses to run
  against an older or unparseable version.
- One-time authentication with Antigravity, performed by `agy` itself outside
  of RepoOps (RepoOps never extracts tokens, impersonates the provider API, or
  automates the GUI — it only spawns the documented headless CLI).

## Model discovery

RepoOps never hard-codes a model catalogue. `agy models` is available for you
to list current models (one identifier per line, no header row observed in
practice); pass the one you want via `--model`.

## Example invocation

```bash
echo "Add input validation to the CSV importer." > task.txt

repoops agent-run /path/to/repo \
  --provider antigravity \
  --model gemini-3.5-flash-low \
  --prompt-file task.txt
```

Internally this runs (never with `--dangerously-skip-permissions` or any other
permission-widening flag):

```bash
agy --model gemini-3.5-flash-low --output-format stream-json \
    --json-schema .repoops/agent-runs/<run_id>/report.schema.json \
    -p "Add input validation to the CSV importer."
```

## What RepoOps records

Each run is written to `.repoops/agent-runs/<run_id>/` inside the target
repository:

- `run.json` — normalized `AgentRunResult`: run id, provider, requested/resolved
  model, session id (`conversation_id`, if exposed), repository, start/end
  timestamps, process exit code, observable tool/action steps, commands
  executed, tool errors, usage/token telemetry (if exposed), the agent's
  structured final report, and deterministic Git evidence.
- `stream.ndjson` — the raw NDJSON event stream, unmodified, for debugging.
- `report.schema.json` — the JSON Schema handed to `agy --json-schema`,
  constraining the agent's final structured answer to `status`, `summary`,
  `verification_reported`, `blockers`, `remaining_risks`, `suggested_next_action`.

Git evidence (`run.json` -> `git_evidence`) is captured independently, before
and after the run, using only the same read-only, stat-only `git status
--porcelain=v1` / `git diff --stat` primitives `repoops scan` and `repoops
checkpoint` already use — never full diff contents. It reports changed files,
newly added files, deleted files, a redacted `diff --stat`, and before/after
dirty state. RepoOps' own `.repoops/agent-runs/<run_id>/` record is excluded
from this evidence (same filter `repoops checkpoint` uses for `.repoops/`), so
a run never shows up as a "changed file" against itself, and the "before"
snapshot is captured before that directory is even created.

RepoOps never commits, pushes, resets, cleans, or stashes. It runs exactly one
task per invocation and never starts a second one automatically.

## Observed real CLI behavior (agy 1.1.10)

Validated directly against a real local install, not assumed. Key points
where the implementation was corrected to match reality:

- **Event envelope.** Each NDJSON line is `{"event": "<type>", "<type>":
  {...payload...}}` — the payload lives under a key matching the event type,
  not flat on the line. `conversation_id` is a top-level sibling on `init` but
  nested *inside* the payload on `step_update` and `result`.
- **Event types actually seen:** `init`, `step_update`, `result`. There is
  **no distinct `tool_error` event**. A failed tool call surfaces as
  unstructured text inside `step_update.tool_info.output`; a fatal run only
  surfaces as `result.status == "ERROR"` with a `result.error` string
  (alongside a non-zero process exit code) — that is the only reliable,
  structured error signal RepoOps parses.
  - Example: `agy --model <bad-model> ...` produces `{"event":"result","result":
    {"status":"ERROR","error":"invalid model selection ...","conversation_id":""}}`
    with exit code 1 and no `structured_output`.
- **`step_update` shape:** `step_index`, `state` (`ACTIVE`/`DONE`, not
  `status`), `step_type` (`user_input`, `agent_response`, `tool`, `checkpoint`,
  `finish`, ...), and for tool steps `tool_name` plus `tool_info: {name,
  parameters, output}`. RepoOps only extracts a shell command string when
  `tool_name == "run_command"`, from `tool_info.parameters.CommandLine`; other
  tools (e.g. `write_to_file`) are recorded as observable steps but don't
  populate `commands_executed`.
- **Resolved model** comes only from `init.<payload>.model`; the `result`
  event does not repeat the model.
- **Usage** keys observed: `input_tokens`, `output_tokens`, `thinking_tokens`,
  `cache_read_tokens`, `total_tokens`.
- **Important operational note, found via a real smoke run:** `agy`'s
  `write_to_file` tool defaulted to writing outside the invoked repository
  (into a per-user scratch directory) even when the prompt explicitly asked
  for the file in "the current working directory." The agent's own
  `structured_output` still reported `"status": "success"`. RepoOps' Git
  evidence correctly showed zero changed files in that run — this is precisely
  the scenario deterministic verification exists to catch. Don't rely on the
  agent's phrasing about *where* it wrote something; check `git_evidence`.

## Agent-reported success vs. RepoOps-verified success

Three distinct concepts, kept separate on purpose:

- `run.json` -> `agent_report` — the agent's own claim (`status`, `summary`,
  etc.). Treated as a report, never as ground truth.
- `run.json` -> `exit_code` — the raw `agy` subprocess exit code.
- `run.json` -> `process_exit_status` — `"success"` iff `exit_code == 0`,
  else `"failed"`. This field is named `process_exit_status`, not
  `repoops_verified_status`, precisely so it doesn't imply RepoOps performed
  any deeper verification than an exit-code check. If the agent claims success
  on a non-zero exit, that mismatch is recorded in `verification_notes`.

RepoOps does **not** run your test suite or any other acceptance check in this
change. Treat `process_exit_status: success` as "the process completed
cleanly," not "the change is correct." Always inspect `git_evidence` (and, as
the real smoke run above shows, don't assume the agent's summary accurately
describes what it actually changed) before trusting the result.

## Current limitations

- Model discovery (`agy models` parsing) takes the first whitespace token per
  non-empty line and skips an optional header/separator row; the real CLI
  currently prints a plain list with no header, but the parser tolerates one.
- `process_exit_status` is exit-code-only; no test execution or deeper
  deterministic verification is performed yet.
- There is no structured tool-level error event in the real CLI; tool failures
  that don't also produce a fatal `result.status == "ERROR"` are only visible
  as free-text inside a step's `tool_info.output`, which RepoOps does not
  parse for error detection.
- Only `antigravity` is supported as a provider today. `AgentRunner` is an
  abstract base so a future `CodexRunner` can implement the same
  `run(task, repo, config) -> AgentRunResult` contract without changing task
  semantics, but it does not exist yet.
- No scheduler, task queue, or autonomous loop — `repoops agent-run` executes
  exactly one task per invocation, driven by a human or an external caller.
