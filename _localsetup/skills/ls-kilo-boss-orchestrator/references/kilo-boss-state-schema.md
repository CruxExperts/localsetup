# Kilo Boss Orchestrator State Schema

## queue.jsonl item

```json
{
  "id": "task-abc123",
  "status": "pending",
  "priority": 100,
  "attempts": 0,
  "max_attempts": 3,
  "command_argv": [
    "kilo",
    "run",
    "--auto",
    "--agent",
    "sidekick",
    "analyze repo"
  ],
  "command": "kilo run --auto --agent sidekick 'analyze repo'",
  "repo_root": "/home/cptnfren/myrig",
  "timeout_seconds": 600,
  "destructive": false,
  "consensus_required": true,
  "worker_primary": "worker-primary",
  "worker_verifier": "worker-verifier",
  "session_id": "session-task-abc123",
  "session_shared": true,
  "session_visibility": "shared-authenticated",
  "created_at": "2026-04-22T12:00:00Z"
}
```

Validation notes:

- `session_id` must be explicitly present and non-empty in task templates.
- enqueue rejects templates missing `session_id`.
- `command_argv` must be a YAML list. Free-form shell command strings are rejected.
- command execution is allowlisted to `kilo run ...` and executed with `shell=False`.

## task file

- path: `.kilo/state/orchestrator/tasks/<task-id>.json`
- status lifecycle: `pending -> running -> done|failed|dead`

## result file

- path: `.kilo/state/orchestrator/results/<task-id>.json`
- includes role, status, exit_code, stdout/stderr, files_changed, timestamps

## lease file

- path: `.kilo/state/orchestrator/leases/<task-id>.lock`
- fields: task_id, worker_id, start_ts, ttl_seconds, status
- expired leases are reclaimed by `watchdog`; running tasks are requeued until `max_attempts`, then deadlettered.

## heartbeat file

- path: `.kilo/state/orchestrator/heartbeats/<worker-id>.json`
- fields: worker_id, current_task, status, last_seen

## session file

- path: `.kilo/state/orchestrator/sessions/<session-id>.json`
- fields: session_id, task_id, session_shared, session_visibility, workers, status, discovered_at, updated_at

## consensus file

- path: `.kilo/state/orchestrator/consensus/<task-id>.json`
- fields: gate_passed, severity, discrepancies, requires_tiebreaker, decided_at
- `finalize` requires `gate_passed: true` and `requires_tiebreaker: false`.

## validation record

- path: `.kilo/state/validation/<task-id>.md`
- written after consensus and final decision
