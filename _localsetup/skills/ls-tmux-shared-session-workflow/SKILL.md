---
name: ls-tmux-shared-session-workflow
description: Server/ops in tmux; use tmux_ops to pick a managed session, probe sudo, and run commands with captured logs. Supports REMOTE_TMUX_HOST for VMs/remote/Docker.
metadata:
  version: "5.1"
---

# tmux shared session workflow (ops)

**Rule:** Any request that involves running commands on the host uses this workflow. Sudo is always assumed required. Use `tmux_ops`; do not infer busy state from `tmux ls` or parse pane capture yourself.

## Tool

From repo root, run `./_localsetup/tools/tmux_ops`. If tmux is on another host, set `REMOTE_TMUX_HOST`; the wrapper runs the same tool over SSH.

Full implementation reference: [_localsetup/docs/ops/tmux-ops-managed.md](../../docs/ops/tmux-ops-managed.md). Remote behavior: [_localsetup/docs/ops/tmux-ops-remote.md](../../docs/ops/tmux-ops-remote.md).

Primary commands:

| Command | Purpose |
|---|---|
| `pick` | Create or select a safe managed `ops*` session and return `session`, `reason`, `state_dir`, and `attach_command`. |
| `probe -t SESSION` | Check sudo readiness. Returns `sudo: "ready"`, `sudo: "password_required"`, or `sudo: "failed"`. |
| `run -t SESSION [--timeout SECS] [--tail N] -- CMD` | Run one command, capture stdout/stderr to a log, and return `run_id`, `exit_code`, `status`, `elapsed_s`, `log_path`, `tail`, and `attach_command`. |
| `status -t SESSION [--run-id ID] [--wait --timeout SECS]` | Read active or completed run status without sending input. |
| `cancel -t SESSION --run-id ID` | Explicitly interrupt the active managed run. |

`send` and `wait` still exist for compatibility/diagnostics, but they are not the normal workflow.

## Sequence

1. Run `./_localsetup/tools/tmux_ops pick`.
2. Show the returned `attach_command` immediately in a copy-paste code block. Do not wait for the user to attach.
3. Run `./_localsetup/tools/tmux_ops probe -t <session>`.
4. If probe returns `sudo: "password_required"`, stop. Ask the user to attach, enter the password in that pane, and reply `sudo ready`.
5. After the user replies `sudo ready`, run probe again. Continue only when probe returns `sudo: "ready"`.
6. Run every command with `./_localsetup/tools/tmux_ops run -t <session> -- <cmd>`.
7. Read the returned `tail` and, when needed, inspect the returned `log_path`.
8. If `run` returns `status: "running"`, the command timed out but is still active. Use `status -t <session> --run-id <run_id> --wait --timeout <secs>` to keep watching, or `cancel -t <session> --run-id <run_id>` if the user explicitly wants it interrupted.
9. If sudo expires later, run `probe` again and repeat the password gate.

## Output Contract

`run` returns JSON similar to:

```json
{
  "run_id": "1778300000-abcd1234ef",
  "session": "ops",
  "exit_code": 0,
  "status": "completed",
  "elapsed_s": 1.234,
  "log_path": "/tmp/localsetup-tmux-ops/ops/logs/1778300000-abcd1234ef.log",
  "tail": "last log lines",
  "attach_command": "tmux new-session -A -s ops"
}
```

Timeouts are not command failures. A timeout returns `status: "running"` and keeps `active.json` live so a second `run` is refused until the command completes or is cancelled.

## Remote

When the tmux server runs on a different host:

- Set `REMOTE_TMUX_HOST` to that host.
- Optionally set `REMOTE_TMUX_CWD` to the repo path on the remote. Default: `/opt/devzone/devops`.
- Use the same `pick`, `probe`, `run`, `status`, and `cancel` commands. Session names, state paths, and logs are on the remote host.

## Hard Rules

1. Host commands run only through `tmux_ops run` after `pick` and `probe`.
2. Stop only when probe returns `password_required` or `failed`.
3. Show `attach_command` immediately after `pick`.
4. Use returned `run_id`, `status`, `tail`, and `log_path`; do not invent a separate sleep or polling strategy.
5. Interrupt only with `tmux_ops cancel -t <session> --run-id <run_id>`.
