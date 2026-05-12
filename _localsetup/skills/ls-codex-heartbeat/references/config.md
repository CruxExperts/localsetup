---
status: ACTIVE
version: 3.4
---

# Heartbeat Config

`config/codex_heartbeat.yaml` is target-repo state created only by `localsetup harness codex-heartbeat init`.

Important fields:

- `heartbeat.enabled`: `false` after init. `enable` flips it to `true`; `disable` flips it back.
- `heartbeat.interval_minutes`: schedule cadence used when upserting `cron/manifest.yaml`.
- `heartbeat.state_dir`: repo-relative runtime artifact directory. Absolute paths and parent traversal are rejected.
- `codex.enabled`: controls whether normal `run` may launch the configured Codex command. `run --no-agent` skips model use.
- `hooks.before` and `hooks.after`: serial argv-list commands with optional `timeout_seconds` and `allow_direct`.
- `direct_command_policy`: blocks direct `git commit`, `git push`, and destructive executables unless explicitly allowed.
