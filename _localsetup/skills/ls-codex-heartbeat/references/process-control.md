---
status: ACTIVE
version: 3.4
---

# Process Control

Commands are launched with a new session where the host supports it. On timeout, the harness terminates the process group, waits briefly, then kills the group if needed.

Direct command policy blocks common destructive executables plus `git commit` and `git push` by default. Hooks plus `direct-argv` and `resolved-path` agent profiles run with `shell=False`; `shell-login` is explicit opt-in compatibility mode and records the rendered command.

Codex execution still runs under the configured agent profile, launcher mode, Codex client configuration, sandbox, and approval settings; the heartbeat harness is not a sandbox replacement.
