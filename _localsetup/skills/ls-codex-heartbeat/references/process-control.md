---
status: ACTIVE
version: 3.4
---

# Process Control

Commands are launched with a new session where the host supports it. On timeout, the harness terminates the process group, waits briefly, then kills the group if needed.

Direct command policy blocks common destructive executables plus `git commit` and `git push` by default. The Codex command still runs under the normal Codex sandbox and approval settings declared in the command argv; the heartbeat harness is not a sandbox replacement.
