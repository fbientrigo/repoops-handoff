# RepoOps Unattended Single-Run Scheduler Guide

RepoOps provides a single-run scheduler primitive (`repoops scheduler-run-once`) designed to safely enable unattended, periodic background execution of task backlog items without running a daemon or resident loop.

---

## Key Architectural Guarantees

1. **One Task Per Invocation**: Each invocation of `repoops scheduler-run-once` executes **at most ONE** eligible task from `.repoops/tasks/`.
2. **Deterministic Locking**: A repository-level lock (`.repoops/locks/scheduler.lock`) prevents two scheduler processes from executing tasks concurrently on the same machine. Stale PIDs are detected and cleaned automatically.
3. **No Automatic Retries**: If a task fails or times out, its attempt count is recorded and it is not automatically retried. Humans or external workflows must explicitly review and requeue tasks.
4. **Hard Execution Timeout**: Agent process execution is guarded by a hard overall timeout (`1800s` by default), terminating timed-out processes cleanly before escalating to kill signals.
5. **Verification-Gated Promotion**: Code changes are promoted to `repoops/integration` **only** if all deterministic acceptance tests and workspace boundary checks pass.
6. **No Daemon Required**: RepoOps never stays resident in memory or runs continuous loops. Native operating system schedulers invoke it periodically.

---

## CLI Usage

```bash
repoops scheduler-run-once <path-to-repo> \
  --provider antigravity \
  --model "Gemini 3.5 Flash (Low)" \
  --max-attempts 1
```

### Options

* `<repo>`: Path inside the target Git repository (default: `.`)
* `--provider`: Agent provider (default: `antigravity`)
* `--model`: Model identifier as reported by `agy models` (required)
* `--max-attempts`: Maximum allowed execution attempts per task (default: `1`)

---

## Machine-Friendly Exit Semantics

| Exit Code | Outcomes | Description |
|---|---|---|
| **`0`** | `task_verified`<br>`no_eligible_task` | A task was executed, verified, and promoted, OR no eligible tasks were waiting in backlog. |
| **`1`** | `task_failed`<br>`task_policy_violation`<br>`task_unverified`<br>`locked`<br>`error` | Execution failed, violated policy, unverified, scheduler was locked by another process, or an unexpected error occurred. |

Detailed machine-readable run records are persisted at:
`.repoops/scheduler-runs/<scheduler_run_id>/run.json`

---

## OS Scheduler Configurations

### 1. Windows Task Scheduler

You can schedule RepoOps to run every 15 minutes using `schtasks` or the Task Scheduler GUI.

#### Command Line (`cmd` / PowerShell as Administrator)

```powershell
schtasks /Create /TN "RepoOps-Scheduler" /TR "repoops scheduler-run-once C:\Users\Asus\Documents\code\3_products\repoops-handoff --model \"Gemini 3.5 Flash (Low)\"" /SC MINUTE /MO 15 /RU "%USERNAME%"
```

#### GUI Setup

1. Open **Task Scheduler** (`taskschd.msc`).
2. Click **Create Basic Task...** and name it `RepoOps-Scheduler`.
3. Set Trigger to **Daily**, recur every 1 day.
4. In Advanced Settings, set **Repeat task every**: `15 minutes`.
5. Set Action to **Start a program**:
   - Program/script: `repoops` (or `C:\Users\Asus\.venv\Scripts\repoops.exe`)
   - Add arguments: `scheduler-run-once C:\path\to\your\repo --model "Gemini 3.5 Flash (Low)"`

---

### 2. Linux / macOS `cron`

Open your crontab editor:

```bash
crontab -e
```

Add a periodic entry (e.g. running every 15 minutes):

```cron
*/15 * * * * /usr/local/bin/repoops scheduler-run-once /path/to/repo --model "Gemini 3.5 Flash (Low)" >> /path/to/repo/.repoops/scheduler.log 2>&1
```

---

## Safety & Troubleshooting

- **Check Scheduler State**:
  Detailed run JSON files are saved under `.repoops/scheduler-runs/<id>/run.json`.
- **Lock Contention**:
  If a previous run is actively executing, subsequent scheduler invocations log `outcome: locked` and exit safely with code 1.
- **Stale Lock Cleanup**:
  If a process crashes abnormally, the next invocation checks if the PID is active. If the PID is dead, the lock is automatically cleared.
