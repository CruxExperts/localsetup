---
status: ACTIVE
version: 3.4
---

# Heartbeat Config

`config/codex_heartbeat.yaml` is target-repo state created only by `localsetup harness codex-heartbeat init`.

## Core fields

- `heartbeat.enabled`: `false` after init. `enable` flips it to `true`; `disable` flips it back.
- `heartbeat.interval_minutes`: schedule cadence used when upserting `cron/manifest.yaml`.
- `heartbeat.state_dir`: repo-relative runtime artifact directory. Absolute paths and parent traversal are rejected.
- `heartbeat.stale_after_seconds`: minimum age before a same-host lock whose recorded PID is no longer live is quarantined. It defaults to 3600 and must be a positive integer.
- `agent.enabled`: controls whether normal `run` may launch the configured agent profile. `run --no-agent` skips that launch.
- `agent.profile`: profile name under `agent_profiles`; the shipped disabled default is `heartbeat`.
- `agent.timeout_seconds`: optional override for the selected profile timeout.

## Agent profiles

Each `agent_profiles.<name>` mapping is client-neutral:

- `client`: non-empty identity label recorded in command evidence. The runtime accepts any framework agent CLI; it does not infer vendor-specific flags.
- `command`: non-empty argv list for that client. With `prompt_transport: argv`, it contains exactly one `{heartbeat_prompt}` argument. `stdin` sends the prompt on standard input; `none` sends no prompt.
- `launcher`: `resolved-path` resolves the first argv element through `path` or `path_env` and runs the absolute executable with `shell=False`; `direct-argv` preserves a fully specified argv list; `shell-login` is opt-in compatibility for profile-managed installs and records the rendered shell command.
- `prompt`: heartbeat instruction string.

The shipped profile is disabled and demonstrates the current Codex non-interactive form `codex exec --json {heartbeat_prompt}`. Replace its `client` label and `command` argv for another framework CLI; do not add client-specific behavior to the heartbeat runtime.

## Hooks and direct-command policy

- `hooks.before` and `hooks.after`: serial argv-list commands with optional `timeout_seconds` and `allow_direct`.
- `direct_command_policy.allow_git_writes`: required for direct `git commit` or `git push`, including commands with Git global options before the subcommand.
- `direct_command_policy.allow_destructive`: required for blocked destructive executable names.
- `direct_command_policy.allowlist` and per-command `allow_direct` do not bypass either prohibition.
