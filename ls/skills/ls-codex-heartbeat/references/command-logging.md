---
status: ACTIVE
version: 3.4
---

# Command Logging

Hooks and configured agent commands run in serial order. Hook commands and `direct-argv` or `resolved-path` profiles execute with `shell=False`; `shell-login` is opt-in and records the rendered command for profile-managed compatibility.

Every executed command and every command blocked by direct-command policy gets a `command-<index>.json` sidecar. The command log records each sidecar filename and SHA-256, while the run manifest commits hashes for `heartbeat-result.json`, `command-log.json`, and every referenced sidecar. Promotion rejects a staged run if a required artifact, reference, or hash is missing or mismatched.

Sidecars record argv, cwd, timeout, launcher metadata, client label, resolved executable when available, PID, process group/session metadata when available, return code, timeout state, errors, and stdout/stderr tails.
