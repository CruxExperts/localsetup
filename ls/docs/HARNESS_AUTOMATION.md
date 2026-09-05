---
status: ACTIVE
version: 4.4
owner_skill: ls-codex-heartbeat
---

# Harness automation

Localsetup's harness pack provides opt-in automation scaffolding for target repositories. The shipped harness profiles are Codex heartbeat and repo-finalizer.

The important boundary is simple: selecting or installing the `harness` pack only installs the capability. It does not create `HEARTBEAT.md`, write `config/codex_heartbeat.yaml`, edit `cron/manifest.yaml`, create `.localsetup/state/codex-heartbeat/`, or schedule autonomous work. A target repo is activated only through explicit harness commands.

## Install the harness capability

```bash
localsetup install --packs harness --tools codex --yes
```

This installs `ls-codex-heartbeat`, `ls-cron-orchestrator`, and `ls-workflow-repo-finalizer` into the managed Localsetup package library. Normal Localsetup install behavior remains user-initiated.

## Activate a target repo

Preview:

```bash
localsetup harness codex-heartbeat plan
```

Initialize local target files with heartbeat disabled:

```bash
localsetup harness codex-heartbeat init
```

`init` creates:

- `HEARTBEAT.md`
- `config/codex_heartbeat.yaml`

The generated config starts with `heartbeat.enabled: false`.

Enable the target heartbeat and upsert the cron manifest:

```bash
localsetup harness codex-heartbeat enable
```

`enable` flips `heartbeat.enabled` to `true`, creates or updates `cron/manifest.yaml`, preserves unrelated triggers and tasks, and validates the manifest through the cron orchestrator.

Installing the live crontab is a separate explicit step:

```bash
localsetup harness codex-heartbeat enable --install-crontab --yes
```

`--install-crontab` without `--yes` is rejected.

## Run and inspect

Run without model use:

```bash
localsetup harness codex-heartbeat run --no-agent
```

Check state:

```bash
localsetup harness codex-heartbeat status
```

Inspect read-only task budget:

```bash
localsetup harness codex-heartbeat budget
```

`budget` reads `config/codex_heartbeat.yaml` and, when configured, a repo-local YAML task queue from `heartbeat.task_queue_path`. It reports policy, summary, and task reservations as JSON. It does not spawn agents, enforce scheduling, commit changes, or activate heartbeat.

Disable without removing history:

```bash
localsetup harness codex-heartbeat disable
```

`disable` flips config back to disabled and disables the heartbeat cron task. It does not delete historical artifacts.

## Repo finalizer profile

Use repo-finalizer to report dirty Git state and optionally stage or checkpoint only allowlisted managed outputs.

Plan and status are read-only:

```bash
localsetup harness repo-finalizer plan
localsetup harness repo-finalizer status --json
```

Run with no mutation:

```bash
localsetup harness repo-finalizer run --no-commit --json
```

Checkpoint commit is explicit and gated:

```bash
localsetup harness repo-finalizer run --checkpoint --message "chore: checkpoint managed outputs"
```

Policy defaults come from built-in settings. If present, `config/localsetup_finalizer.yaml` overrides classification and stage allowlists. Repo-finalizer never runs `git push`, `git reset`, or delete/revert commands.

`run` writes the latest JSON and text reports under the repo-local ignored state directory:

```text
.localsetup/state/repo-finalizer/latest.json
.localsetup/state/repo-finalizer/latest.md
```

When only runtime-ignored finalizer state is present, status reports `clean_except_ignored` instead of blocking cleanup.

## Runtime artifacts

Runtime state stays in the target repo under:

```text
.localsetup/state/codex-heartbeat/
```

Each run starts under `runs/<run-id>.staged`. The harness writes `manifest.json`, `heartbeat-result.json`, and `command-log.json`, validates artifact hashes, then atomically promotes the staged directory to `runs/<run-id>`. A run is not successful until that validation and promotion finish.

Pointers stay relative to the state directory:

- `active.json` tracks a currently staged run.
- `latest.json` points to the most recently promoted run and records the manifest hash.
- `heartbeat.lock` prevents concurrent runs.

Interrupted staged runs are preserved as recovered failures before a fresh run starts.

## Command and agent boundary

Hooks and launch commands run in serial order with explicit timeouts, stdout/stderr tails, sidecar JSON logs, PID/process group/session metadata where available, and manifest hashes. Hooks plus `direct-argv` and `resolved-path` agent profiles run with `shell=False`; `shell-login` is explicit opt-in compatibility mode and records the rendered command.

Direct hook policy blocks `git commit`, `git push`, and common destructive executables unless the target config explicitly allows them.

Agent execution is additionally constrained by the configured agent profile, launcher mode, selected agent-client configuration, sandbox, and approval settings. The heartbeat harness records and gates execution; it does not replace an agent client's sandbox or approval model.

## Cron launcher

Cron entries use the registered Localsetup source checkout through the Localsetup Python launcher, for example:

```text
python3 /path/to/localsetup/ls/tools/localsetup.py --source-root /path/to/localsetup --target-directory /path/to/target harness codex-heartbeat run --no-agent
```

The command does not hard-code `ls/skills/...` inside the target repo.
