---
status: ACTIVE
version: 3.4
---

# Process Control

Commands are launched with a new session where the host supports it. On timeout, the harness terminates the process group, waits briefly, then kills the group if needed.

Direct command policy blocks common destructive executables plus `git commit` and `git push` by default, including Git commands with supported global options before the subcommand. Hooks plus `direct-argv` and `resolved-path` profiles run with `shell=False`; `shell-login` is explicit opt-in compatibility mode and records the rendered command.

The heartbeat runtime executes only the configured agent profile’s argv and records its client label and launcher metadata. It does not supply client-specific model, sandbox, approval, or authentication semantics, and it is not a sandbox replacement.
