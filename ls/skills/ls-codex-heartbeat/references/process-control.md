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

## LSCli receipt validation foundation

The internal LSCli process adapter accepts success only when a zero process exit
agrees with a complete schema-version-1 JSONL receipt: contiguous sequence
numbers, one start, matching task/session identifiers, and one completed result
with a checkpoint digest. Missing, truncated, duplicated, unknown, or trailing
events fail validation. A completion string in ordinary output is insufficient.
Unexpected approval requests fail because this adapter has no approval channel.

Protocol mode discards raw stdout and stderr after bounded validation; its
metadata contains identities, status, sequence, and checkpoint, not result text.
Its optional activity deadline advances only on complete valid start/progress
frames. Stderr noise and partial frames do not reset it. This bounds protocol
inactivity, not semantic progress or repeated unproductive tasks. Neither a
receipt nor its saved metadata grants authority or closes an issue.

Typed LSCli profiles use the protected registered launcher and coding receipt.
Run/compaction budget integration still requires its remaining gates; generic
profiles retain their existing process contract.

## Compound continuation evidence

The internal compaction receipt adapter accepts one JSON object of at most
16 KiB, with exactly schema_version (integer 1), source_checkpoint, checkpoint,
profile, and usage. Digests use the existing checkpoint format. Source and
profile must match the selected action; destination must differ from source.
Usage retains the compaction owner's one-request, zero-tool and allocated-token
checks. Duplicate keys, extra objects, malformed/truncated output and nonzero
process exits cannot establish completion. Partial output does not count as
streaming progress. The bounded process pump suppresses raw output tails when
using this adapter.

Successful process output is only candidate evidence. Before continuation, a
caller holding the matching task/session lease must verify the private owned
compaction receipt file, its agreement with process output, and both source and
destination checkpoints through the existing session owner. Missing, unsafe,
interrupted, incompatible or uncertain history fails; this verifier never
chooses a latest checkpoint, repairs evidence or replays an operation. It returns
only the verified destination digest and preserves the source history.

This adapter and verifier prepare compound execution. They do not yet select or
dispatch heartbeat phases, reserve a budget, or authorize a provider call. Those
steps must bind the explicit action and allocation before invoking either phase.
