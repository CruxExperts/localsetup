# Kilo Boss Orchestrator Runbook

## Purpose

Operate a repo-local boss-worker gentle loop for Kilo headless execution with consensus validation and watchdog recovery.

## State root

- `.kilo/state/orchestrator/`

## Basic workflow

1. Initialize state:

```bash
python3 scripts/boss_ctl.py init
```

2. Enqueue task card:

```bash
python3 scripts/boss_ctl.py enqueue --task-file references/examples/task.sample.yaml
```

3. Dispatch work:

```bash
python3 scripts/boss_ctl.py dispatch --max-dispatch 1
```

Session tracking requirement:

- every task card must include `session_id` (hard validation on enqueue),
- dispatcher records session metadata under `.kilo/state/orchestrator/sessions/`,
- workers receive `--session-id` and propagate it to result artifacts and failure-routing metadata,
- session visibility defaults to `shared-authenticated` to support cross-terminal continuation on authenticated Kilo environments.

4. Inspect status:

```bash
python3 scripts/boss_ctl.py status
```

5. Evaluate consensus:

```bash
python3 scripts/boss_ctl.py consensus --task-id <task-id>
```

6. Finalize task if gate passed:

```bash
python3 scripts/boss_ctl.py finalize --task-id <task-id>
```

## Watchdog

Run periodically to reclaim orphan lease files:

```bash
python3 scripts/boss_ctl.py watchdog
```

## Phase-1 deterministic retry recovery (offline-safe)

When transient orchestrator failures occur and no AI fallback model is available, run the retry watchdog:

```bash
python3 scripts/kilo_retry_watchdog.py \
  --session ops \
  --retry-interval-seconds 15 \
  --max-retries 4 \
  --tail-lines 50 \
  --state-root .kilo/state/orchestrator \
  --hermes-outbox .kilo/state/hermes/outbox
```

Enhanced deadman behavior (phase-1.1):

- scans orchestrator logs for failure markers,
- applies single-instance lock guard (`retry_watchdog.lock`) before any recovery action,
- if lock is active and not stale, skips run to avoid concurrent mutation races,
- stale lock reclamation is automatic after `--lock-stale-seconds`,
- applies a deterministic multi-strategy ladder per attempt:
  1) prompt nudge,
  2) interrupt + prompt,
  3) restart in existing tmux session,
  4) recreate session + relaunch,
- detects edge cases (missing tmux session, Kilo process inactive, pane unresponsive/frozen),
- enforces single-instance lock to prevent concurrent watchdog races,
- waits startup grace window, then nudges resume again,
- emits JSON payload for Hermes under `.kilo/state/hermes/outbox/` if retry budget is exhausted.

Useful flags:

```bash
--restart-on-unhealthy \
--kilo-launch-command "kilo" \
--startup-grace-seconds 6 \
--unresponsive-threshold-seconds 45 \
--lock-stale-seconds 300
```

Hermes payload includes telemetry bundle for debugging/routing:

- host identity and platform,
- tmux session + command + health snapshot,
- state/log paths and log file metadata,
- strategies attempted and outcomes,
- recent log tails.


## Validation record

Write a compact validation record after each consensus decision:

```bash
python3 scripts/boss_ctl.py write-validation --task-id <task-id> --outcome pass --notes "primary/verifier matched"
```

## Safety notes

- Use guarded execution defaults for risky operations.
- Never place mutable runtime state under `_localsetup/`.
- Keep docs and indexes synchronized after policy or workflow changes.
