---
name: ls-workflow-ops-tmux-session
description: Use when commands need sudo, root/admin elevation, require_escalated, pseudo-terminal/PTY handling, interactive sudo or elevated terminal password prompts, or managed tmux run tracking.
metadata:
  version: "1.0"
---

Use this workflow package for server or remote ops through tmux wrappers.
Primary source references: `ls/docs/ops/tmux-ops-managed.md` and `ls/docs/ops/tmux-ops-remote.md`. Installed packages expose the same references through the `localsetup://doc/ops/tmux-ops-managed.md` and `localsetup://doc/ops/tmux-ops-remote.md` aliases.

## When to use

Use this workflow when a command needs `sudo`, root/admin elevation, `require_escalated`, pseudo-terminal/PTY behavior, interactive sudo or elevated terminal password prompt handoff, or durable managed tmux run tracking through `ls/tools/tmux_ops`. Installed packages expose that tool through the `localsetup://tool/tmux_ops` alias.

Do not use this workflow for normal repo-local coding, API authentication, token setup, non-privileged file edits, or commands that can run safely without managed terminal state.

## Execution authorization boundary

Tmux is only the elevated or PTY transport. Session selection, a successful probe, an attached operator, `sudo ready`, and cached sudo credentials do not authorize a command.

Before every managed `run`, require one of these records:

1. **Verified guarded handoff:** Accept a record from `ls-workflow-ops-guarded` only when it contains the exact command or edit and values, exact target, risk classification, likely consequences and affected scope, backup or no-backup decision, rollback action, and the user's immediate explicit approval. Verify that every recorded value still matches the pending payload.
2. **Direct safety gate:** Apply `ls-safety-and-backup` directly and record the same exact command or edit and values, target, risk classification, consequences and affected scope, backup or no-backup decision, and rollback action. Then show that frozen payload to the user and obtain immediate explicit approval for it before execution.

Reject a missing, incomplete, stale, or changed record. Return to the applicable approval workflow and do not run the command. Each managed `run` needs its own still-matching record; approval for one payload does not authorize another.

## Sequence

1. Establish the execution authorization record above for the exact pending payload.
2. Run `./ls/tools/tmux_ops pick` and show the returned attach command.
3. Run `./ls/tools/tmux_ops probe -t <session>`.
   - If the response includes `"action_required": true` or `"sudo": "password_required"`, stop.
   - Tell the user to attach with the returned `attach_command`, run `sudo -v` in that exact tmux pane, enter the password, then reply `sudo ready`.
   - Wait for the user to say `sudo ready` before probing again.
4. Reconfirm that the authorized payload still exactly matches, then run it with `./ls/tools/tmux_ops run -t <session> -- <cmd>`.
5. Track long commands with `./ls/tools/tmux_ops status -t <session> --run-id <id>`.
6. Interrupt only with `./ls/tools/tmux_ops cancel -t <session> --run-id <id>`.

Use the returned `run_id`, `status`, `tail`, and `log_path` as evidence.

## Sudo keepalive

For active privileged work where the user has already entered sudo in the same managed pane, use bounded one-shot keepalive commands instead of ad hoc loops.

1. Request a marker only after `probe` reports sudo `ready`:

   ```bash
   ./ls/tools/tmux_ops keepalive request -t <session> --owner <id> --ttl-seconds 7200 --max-refreshes 24 --reason "<reason>"
   ```

2. Refresh only as an explicit one-shot action while privileged work remains active and the managed pane is idle between commands:

   ```bash
   ./ls/tools/tmux_ops keepalive refresh -t <session>
   ```

3. Report state with `./ls/tools/tmux_ops keepalive status -t <session>`.
4. Clear the marker with `./ls/tools/tmux_ops keepalive clear -t <session> --owner <id>` when privileged work ends.

Keepalive is restricted to managed `ops*` sessions, caps TTL at 7200 seconds and refreshes at 24, and runs only hard-coded `sudo -n -v` during refresh. It must not start a background loop, prompt for a password, or refresh while a managed run is active, another refresh is in progress, or the pane is not idle.
