---
status: ACTIVE
version: 3.4
---

# Command Logging

Hooks and launch commands run in serial order. Hook commands and `direct-argv` or `resolved-path` agent profiles execute with `shell=False`; `shell-login` profiles are opt-in and run a recorded `bash -lc` style command for compatibility with profile-managed installs.

Every command gets a sidecar JSON file with argv, cwd, timeout, launcher mode, resolved executable when available, model policy, PID, process group/session metadata when available, return code, timeout state, and stdout/stderr tails.

The run manifest stores hashes for committed artifacts so corrupt staged output cannot be promoted as a successful run.
