---
status: ACTIVE
version: 4.2
owner_package: ls-workflow-ops-tmux-session
---

# Tmux ops managed workflow

**Purpose:** Explain the managed `tmux_ops` implementation for humans and give agents a deterministic command flow for host operations.

Managed tmux ops keeps host commands visible to the operator, resumable after agent disconnects, and safe around sudo prompts. The normal path is:

```text
pick -> probe -> run -> status
```

`send` and `wait` still exist for older callers, but new agent instructions should use `run` for commands and `status` for follow-up.

## What changed

The managed implementation replaces prompt-regex polling as the primary path.

- `pick` creates a real detached session when no safe `ops*` session exists.
- Existing sessions are reused only when they are managed and idle.
- If every `ops*` session is active, busy, or unmanaged, `pick` returns an error instead of selecting a busy pane.
- Managed sessions use a small bash prompt hook that signals `tmux wait-for` when the prompt is actually reached.
- `run` writes a generated shell script, captures stdout and stderr through `tee`, records status JSON, and returns a log tail.
- A timeout means the command is still running. It is not reported as command failure.
- A second `run` is refused while `active.json` exists for that session.
- Interruption is explicit through `cancel --run-id`.
- `keepalive` records bounded sudo refresh intent and performs only single explicit refreshes with hard-coded `sudo -n -v`.

## State layout

Managed state lives outside the repo:

```text
/tmp/localsetup-tmux-ops/<session>/
  active.json
  idle.json
  managed.json
  pane-operation.lock
  probe.sh
  probe.status.json
  keepalive.json
  keepalive-refresh-<id>.sh
  keepalive-refresh-<id>.status.json
  last_run_id
  <run_id>.status.json
  logs/<run_id>.log
  scripts/<run_id>.sh
```

The session directory is returned as `state_dir` by `pick`. Logs and generated scripts are intentionally in `/tmp`, not in the repository.

## Human workflow

1. Pick a session:

   ```bash
   ./ls/tools/tmux_ops pick
   ```

2. Attach if you want to watch or enter a sudo password:

   ```bash
   tmux new-session -A -s ops
   ```

   Use the exact `attach_command` returned by `pick`; the session may be `ops`, `ops1`, or another managed `ops*` name.

3. Probe sudo:

   ```bash
   ./ls/tools/tmux_ops probe -t ops
   ```

4. If the probe says `password_required` or `action_required: true`, attach with the returned `attach_command`, run `sudo -v` in that exact tmux pane, enter the password, then tell the agent `sudo ready` so it can probe again.

5. Run commands:

   ```bash
   ./ls/tools/tmux_ops run -t ops -- sudo apt update
   ```

6. Read the returned `tail` first. If you need more context, read the returned `log_path`.

7. If the command is still active:

   ```bash
   ./ls/tools/tmux_ops status -t ops --run-id <run_id> --wait --timeout 120
   ```

8. Cancel only when you intend to interrupt that exact run:

   ```bash
   ./ls/tools/tmux_ops cancel -t ops --run-id <run_id>
   ```

9. For long privileged maintenance, request bounded keepalive only after sudo is ready:

   ```bash
   ./ls/tools/tmux_ops keepalive request -t ops --owner agent-id --ttl-seconds 7200 --max-refreshes 24 --reason "active privileged maintenance"
   ```

   Refreshes are one-shot calls, not a background loop:

   ```bash
   ./ls/tools/tmux_ops keepalive refresh -t ops
   ```

## Agent workflow

Agents should follow this script exactly:

1. Run `./ls/tools/tmux_ops pick`.
2. Parse JSON. If it has `error`, report the error and stop.
3. Show `attach_command` to the user in a copy-paste code block.
4. Run `./ls/tools/tmux_ops probe -t <session>`.
5. If `action_required` is `true` or `sudo` is `password_required`, tell the user to attach with the returned `attach_command`, run `sudo -v` in that exact tmux pane, enter the password, and reply `sudo ready`. Do not run commands yet.
6. After `sudo ready`, run `probe` again.
7. If `sudo` is `failed`, report `detail` and stop.
8. If `sudo` is `ready`, run exactly one logical command with:

   ```bash
   ./ls/tools/tmux_ops run -t <session> -- <command>
   ```

9. Check `status`:
   - `completed`: read `exit_code`, `tail`, and `log_path`; continue only after verifying the result.
   - `running`: keep the `run_id`; use `status --wait` to continue watching.
10. Start another `run` only after the active run has completed or the user explicitly asks to cancel it.
11. Interrupt only with:

   ```bash
   ./ls/tools/tmux_ops cancel -t <session> --run-id <run_id>
   ```
12. If privileged work must keep the same sudo timestamp alive, request a bounded marker only after sudo is `ready`:

   ```bash
   ./ls/tools/tmux_ops keepalive request -t <session> --owner <id> --ttl-seconds 7200 --max-refreshes 24 --reason "<reason>"
   ```

   Run `keepalive refresh -t <session>` only as an explicit one-shot refresh while the work is active and the managed pane is idle between commands. Check `keepalive status -t <session>` for heartbeat/reporting, and end it with `keepalive clear -t <session> --owner <id>`.

## Command reference

| Command | Use | Important fields |
|---|---|---|
| `pick` | Select or create a managed session. | `session`, `reason`, `state_dir`, `attach_command` |
| `probe -t SESSION` | Classify sudo state without fixed sleeps. | `sudo`, `detail`, `attach_command` |
| `run -t SESSION [--timeout SECS] [--tail N] -- CMD` | Run one command and capture logs/status. | `run_id`, `status`, `exit_code`, `elapsed_s`, `log_path`, `tail` |
| `status -t SESSION [--run-id ID] [--wait --timeout SECS]` | Observe active or completed runs without sending input. | same fields as `run` |
| `cancel -t SESSION --run-id ID` | Send the only supported interrupt for an active run. | `run_id`, `status`, `cancel_sent` |
| `keepalive request -t SESSION --owner ID --ttl-seconds N --max-refreshes N --reason TEXT` | Record bounded sudo refresh intent for a managed session with a ready sudo gate. | `state`, `owner`, `expires_at`, `refresh_count`, `max_refreshes`, `attach_command` |
| `keepalive refresh -t SESSION` | Run one hard-coded `sudo -n -v` refresh in the managed pane. | `state`, `last_refresh_ok`, `refresh_count`, `disabled_reason` |
| `keepalive status [-t SESSION]` | Report one or all keepalive markers without running sudo. | `ok`, `sessions`, `seconds_remaining`, `last_refresh_ok` |
| `keepalive clear -t SESSION --owner ID` | Disable a marker only when the owner matches. | `state`, `disabled_reason` |
| `keepalive sweep` | Disable expired or invalid markers without running sudo. | `ok`, `sessions` |

## JSON examples

Pick:

```json
{
  "session": "ops",
  "reason": "created",
  "state_dir": "/tmp/localsetup-tmux-ops/ops",
  "attach_command": "tmux new-session -A -s ops"
}
```

Completed run:

```json
{
  "run_id": "1778300000-abcd1234ef",
  "session": "ops",
  "status": "completed",
  "exit_code": 0,
  "elapsed_s": 1.234,
  "log_path": "/tmp/localsetup-tmux-ops/ops/logs/1778300000-abcd1234ef.log",
  "tail": "last log lines",
  "attach_command": "tmux new-session -A -s ops"
}
```

Timed-out but still running:

```json
{
  "run_id": "1778300000-abcd1234ef",
  "session": "ops",
  "status": "running",
  "exit_code": null,
  "elapsed_s": 30.001,
  "log_path": "/tmp/localsetup-tmux-ops/ops/logs/1778300000-abcd1234ef.log",
  "tail": "partial output"
}
```

## Timeout and cancellation semantics

`--timeout` is the time the tool waits for completion before returning to the agent. It is not a kill timer.

When `run` returns `status: "running"`:

- The command is still active in tmux.
- `active.json` remains live.
- A second `run` returns `error: "run already active"`.
- `status --wait` can keep watching the same `run_id`.
- `cancel --run-id` is the only documented interrupt path.

## Sudo semantics

`probe` checks `sudo -Nnv` first and falls back to `sudo -vn` only when `-N` is unsupported. It never sends `sudo -v` automatically.

- `ready`: cached sudo credentials are available; continue.
- `password_required`: the user must attach to the returned tmux session, run `sudo -v` in that pane, enter the password, then have the agent probe again.
- `failed`: sudo is unavailable or denied; report `detail` and stop.

Do not treat a shell prompt as proof of sudo readiness. Trust the `probe` JSON. `tmux_ops run` also checks for a fresh `ready` sudo gate before sending a command and refuses without creating run state when sudo action is required.

`tmux_ops keepalive` exists only for active privileged work in managed `ops*` sessions. It does not start a loop, alter sudo policy, or read command strings from marker files. `request` caps TTL at 7200 seconds and refreshes at 24, records the current pane identity when available, and requires a ready sudo gate in that same pane. `refresh` validates the marker, expiry, refresh count, managed session, recorded pane identity, active-run state, pane idleness, and per-session refresh lock before running a generated script whose only sudo command is hard-coded `sudo -n -v`. If the pane is busy, another refresh is in progress, or a managed run is active, refresh returns `action_required: true` without sending input. If the sudo refresh fails or times out, the marker is disabled and agents should stop refreshing and hand control back to the user. `status`, `sweep`, and `clear` never run sudo; `status` and `sweep` disable expired active markers before reporting them.

`pane-operation.lock` is a short-lived guard around managed `send-keys` operations. If a process is killed while holding it, later `run`, `probe`, or `keepalive refresh` calls will report that a pane operation is already in progress. Remove the stale lock only after confirming no `tmux_ops` process is still active for that session.

## Remote hosts

For remote tmux servers, set `REMOTE_TMUX_HOST` and use the same commands. See [tmux-ops-remote.md](tmux-ops-remote.md).

## Legacy commands

`send` and `wait` remain available for compatibility and low-level diagnostics. They are not the normal documented path because they do not provide the managed run status, active-run lock, generated logs, or explicit cancellation contract.
