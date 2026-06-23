---
name: ls-workflow-ops-tmux-session
description: Use when commands need sudo, root/admin elevation, require_escalated, pseudo-terminal/PTY handling, interactive sudo or elevated terminal password prompts, or managed tmux run tracking.
metadata:
  version: "1.0"
---

Use this workflow package for server or remote ops through tmux wrappers.
Primary references: `localsetup://doc/ops/tmux-ops-managed.md` and `localsetup://doc/ops/tmux-ops-remote.md`.

## When to use

Use this workflow when a command needs `sudo`, root/admin elevation, `require_escalated`, pseudo-terminal/PTY behavior, interactive sudo or elevated terminal password prompt handoff, or durable managed tmux run tracking through `localsetup://tool/tmux_ops`.

Do not use this workflow for normal repo-local coding, API authentication, token setup, non-privileged file edits, or commands that can run safely without managed terminal state.

## Sequence

1. Run `localsetup://tool/tmux_ops pick` and show the returned attach command.
2. Run `localsetup://tool/tmux_ops probe -t <session>`.
   - If the response includes `"action_required": true` or `"sudo": "password_required"`, stop.
   - Tell the user to attach with the returned `attach_command`, run `sudo -v` in that exact tmux pane, enter the password, then reply `sudo ready`.
   - Wait for the user to say `sudo ready` before probing again.
3. Run commands with `localsetup://tool/tmux_ops run -t <session> -- <cmd>`.
4. Track long commands with `localsetup://tool/tmux_ops status -t <session> --run-id <id>`.
5. Interrupt only with `localsetup://tool/tmux_ops cancel -t <session> --run-id <id>`.

Use the returned `run_id`, `status`, `tail`, and `log_path` as evidence.
