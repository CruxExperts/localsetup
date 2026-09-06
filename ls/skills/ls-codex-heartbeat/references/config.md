---
status: ACTIVE
version: 3.4
---

# Heartbeat Config

`config/codex_heartbeat.yaml` is target-repo state created only by `localsetup harness codex-heartbeat init`.

## Core fields

- `heartbeat.enabled`: `false` after init. `enable` flips it to `true`; `disable` flips it back.
- `heartbeat.interval_minutes`: integer cron cadence; minute values below 60 must
  divide 60 evenly, and larger values must be whole hours that divide 24.
  Examples: 15 minutes, 120 minutes, 480 minutes, or 1440 minutes. Values such as
  35, 90, and 420 are refused before enabling; strings and booleans are invalid.
- `heartbeat.state_dir`: repo-relative runtime artifact directory. Absolute paths and parent traversal are rejected.
- `heartbeat.stale_after_seconds`: minimum age before a same-host lock whose recorded PID is no longer live is eligible for reclamation under the [recovery contract](recovery.md). It defaults to 3600 and must be a positive integer.
- `agent.enabled`: controls whether normal `run` may launch the configured agent
  profile. `run --no-agent` skips profile loading and executable resolution as
  well as launch. Hooks and transaction validation still run. A disabled heartbeat
  returns before command planning unless explicitly forced.
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


## Cadence and stored schedules

The generated schedule follows wall-clock fields, starting at minute zero for
whole-hour intervals and midnight for daily execution. It is not a monotonic
timer measured from activation or the previous run's completion. The harness
does not emit a timezone override: the installed cron daemon's configured
timezone and clock-change behavior apply. Daylight-saving transitions can change
elapsed spacing; consult that daemon's documentation before activation.
[Crontab field semantics](https://www.man7.org/linux/man-pages/man5/crontab.5.html)
and [Cronie clock-change handling](https://www.man7.org/linux/man-pages/man8/crond.8.html)
describe why field steps do not imply arbitrary elapsed-minute intervals.

Inspection and disabling do not rewrite a stored trigger's schedule. Re-enabling
explicitly regenerates the heartbeat trigger from the validated interval.
Unrelated triggers/tasks and historical heartbeat identifiers remain intact.
Existing unsupported intervals are not silently rounded or migrated.

## Typed LSCli profile

The shipped `lscli-heartbeat` example is unselected and disabled. Replace every
/explicit/... path and the provider profile name with your reviewed setup,
then deliberately select `agent.profile=lscli-heartbeat` and set
`agent.enabled=true` for manual agent runs. Heartbeat enablement remains a
separate switch. Generated cron commands still request `--no-agent`; changing a
recurring job's authority requires its own explicit schedule decision.

This profile uses `client=lscli` and `launcher=lscli` and requires exactly the
fields shown in the template. Generic command, shell, PATH overrides,
prompt-transport overrides, and allow_direct are rejected. All six paths must
be absolute and canonical. The executable must be an owned registered command
for the explicitly supplied runtime root. The framework validates its receipt
and selected runtime, then invokes the protected dispatcher directly.

The provider profile name accepts 1–256 characters. Prompt text must be nonempty,
at most 128 KiB of UTF-8, and is sent only through stdin. It does not appear in
command plans or result sidecars. Workspace is always the heartbeat target.
The grant separately authorizes file access, writes, disclosure, and recipes;
mentioning HEARTBEAT.md in a prompt grants none of these permissions.

Limits are strict integers: timeout 1–3600 seconds, requests 1–64, tools 0–256,
tokens 1–1048576, protocol inactivity 1–3600 seconds (at most the coding timeout),
and combined output 1024–4194304 bytes. An explicit `agent.timeout_seconds`
overrides the profile timeout and must satisfy the same bounds. The outer
process deadline adds 20 seconds for protected startup and terminal delivery;
registration qualification has separate bounded lock waits before process
launch. Only valid protocol start/progress events reset inactivity. The coding
runtime enforces request/tool/token limits and its existing fixed resource
limits; the outer runner independently bounds output and process lifetime.

No credentials are discovered by planning. Runs require the selected provider's
explicit credential configuration and a qualified delegated sandbox backend.
Approval requests are rejected because this profile has no interactive approval
channel. Completion requires both valid JSONL and process success; it does not
mean the controller accepted an issue. Each run starts a new session; automatic
resume, compaction, and semantic no-progress policy remain separate integrations.

Use the owning framework's harness command. A copied standalone skill without
the framework cannot resolve this launcher; ambient framework imports are refused.
