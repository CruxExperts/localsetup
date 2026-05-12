---
status: ACTIVE
version: 3.4
---

# Command Logging

Hooks and launch commands run in serial order with `shell=False`. Every command gets a sidecar JSON file with argv, cwd, timeout, PID, process group/session metadata when available, return code, timeout state, and stdout/stderr tails.

The run manifest stores hashes for committed artifacts so corrupt staged output cannot be promoted as a successful run.
