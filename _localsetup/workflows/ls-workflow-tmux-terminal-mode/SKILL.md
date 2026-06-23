---
name: ls-workflow-tmux-terminal-mode
description: Use when enabling, disabling, defaulting, or checking tmux terminal mode; do not use for one-off sudo or interactive password handoff.
metadata:
  version: "1.0"
---

Use this workflow package for tmux terminal mode setup, defaults, and checks. It manages whether terminal sessions are launched under tmux by default; for one-off `sudo`, elevated permission, PTY, or interactive password handoff, use `ls-workflow-ops-tmux-session`.

Primary references: `localsetup://doc/TMUX_TERMINAL_MODE.md` and `localsetup://tool/tmux_terminal_mode`.
