---
status: ACTIVE
version: 3.4
---

# Heartbeat Artifacts

Runtime artifacts live under `state/codex-heartbeat/` in the target repository.

Each run starts as `runs/<run-id>.staged`. A run is successful only after `manifest.json`, `heartbeat-result.json`, and `command-log.json` validate and the staged directory is atomically promoted to `runs/<run-id>`.

Pointers:

- `active.json`: points at the staged run while work is active.
- `latest.json`: points at the most recently promoted run and records the manifest hash.
- `heartbeat.lock`: prevents concurrent runs.

Pointers must stay relative to the heartbeat state directory. Absolute paths and parent traversal are rejected.
