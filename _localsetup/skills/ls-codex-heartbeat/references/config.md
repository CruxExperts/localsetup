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
- `codex.enabled`: controls whether normal `run` may launch the configured Codex agent profile. `run --no-agent` skips model use.
- `codex.profile`: profile name under `agent_profiles`; the shipped default is `heartbeat`.
- `agent_profiles.<name>.launcher`: `resolved-path` resolves `command_name` through configured PATH or the process PATH and executes the absolute binary with `shell=False`; `direct-argv` preserves a fully specified argv list; `shell-login` is opt-in compatibility for profile-managed installs and records the rendered shell command.
- `agent_profiles.<name>.model`: optional model pin. When null, the Codex client configuration chooses the effective model.
- `agent_profiles.<name>.model_policy`: human-readable policy recorded in command logs, such as `configurable-low-cost`.
- `hooks.before` and `hooks.after`: serial argv-list commands with optional `timeout_seconds` and `allow_direct`.
- `direct_command_policy`: blocks direct `git commit`, `git push`, and destructive executables unless explicitly allowed.

Codex heartbeat jobs use the Codex client's configured default model unless a profile pins `model`. Current OpenAI guidance is to choose the model based on cost, latency, and reasoning needs; `gpt-5.4-mini` is suitable for lower-cost heartbeat or subagent work, but it should be a configurable choice rather than a permanent framework default.
