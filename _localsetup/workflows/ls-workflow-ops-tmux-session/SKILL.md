---
name: ls-workflow-ops-tmux-session
description: Run guarded operations through managed tmux sessions with explicit run tracking.
---

Use this workflow package for server or remote ops through tmux wrappers.
Primary references: `localsetup://doc/ops/tmux-ops-managed.md` and `localsetup://doc/ops/tmux-ops-remote.md`.

## Sequence

1. Run `localsetup://tool/tmux_ops pick` and show the returned attach command.
2. Run `localsetup://tool/tmux_ops probe -t <session>` and stop if sudo needs a password.
3. Run commands with `localsetup://tool/tmux_ops run -t <session> -- <cmd>`.
4. Track long commands with `localsetup://tool/tmux_ops status -t <session> --run-id <id>`.
5. Interrupt only with `localsetup://tool/tmux_ops cancel -t <session> --run-id <id>`.

Use the returned `run_id`, `status`, `tail`, and `log_path` as evidence.
