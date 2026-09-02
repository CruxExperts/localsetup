---
status: ACTIVE
version: 3.4
---

# Heartbeat Artifacts

Runtime artifacts live under `.localsetup/state/codex-heartbeat/` in the target repository.

Each run starts as `runs/<run-id>.staged`. Promotion requires valid hashes for `manifest.json`, `heartbeat-result.json`, `command-log.json`, and every command sidecar referenced by the command log.

Pointers and lock evidence:

- `active.json`: points at the staged run while work is active.
- `latest.json`: points at the most recently promoted run and records the manifest hash.
- `heartbeat.lock`: prevents concurrent runs.

Pointers and artifact references must stay relative to their heartbeat-state base. Absolute paths and parent traversal are rejected.
