---
status: ACTIVE
version: 3.4
---

# Process Control

Commands are launched with a new session where the host supports it. On timeout, the harness terminates the process group, waits briefly, then kills the group if needed.

Direct command policy blocks common destructive executables plus `git commit` and `git push` by default, including Git commands with supported global options before the subcommand. Hooks plus `direct-argv` and `resolved-path` profiles run with `shell=False`; `shell-login` is explicit opt-in compatibility mode and records the rendered command.

The heartbeat runtime executes only the configured agent profile’s argv and records its client label and launcher metadata. It does not supply client-specific model, sandbox, approval, or authentication semantics, and it is not a sandbox replacement.

## Bounded process I/O

The runner drains stdout and stderr incrementally with a combined 4 MiB output
budget. Exceeding it stops the command with termination_reason=output_limit;
sidecars retain at most 12,000 decoded characters per stream. Prompt stdin is
limited to 128 KiB of UTF-8 and is closed after delivery. Commands without an
explicit prompt receive closed input instead of inheriting the controller's
terminal. The monotonic timeout includes stdin delivery, output draining, and
waiting for process exit.

Timeout, SIGINT, and SIGTERM stop the original process group with TERM and then
KILL, with bounded grace and reap waits. Sidecars distinguish the effective
returncode (124 for timeout, 130/143 for cancellation) from the observed
process_returncode. cleanup_reaped reports only whether the direct child was
reaped; it does not prove that an escaped descendant has terminated. A generic
hook is not sandboxed. Descendants retaining output pipes cannot extend the
deadline indefinitely. Signal handling applies to the normal main-thread CLI
execution and restores the prior handlers afterward.

These process outcomes alone do not validate an agent's structured completion
protocol or establish controller acceptance of a task or issue.
