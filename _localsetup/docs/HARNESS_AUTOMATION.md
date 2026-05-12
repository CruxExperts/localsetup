---
status: ACTIVE
version: 3.5
---

# Harness automation

Localsetup's harness pack provides opt-in automation scaffolding for target repositories. The first shipped harness is the Codex heartbeat.

The important boundary is simple: selecting or installing the `harness` pack only installs the capability. It does not create `HEARTBEAT.md`, write `config/codex_heartbeat.yaml`, edit `cron/manifest.yaml`, create `state/codex-heartbeat/`, or schedule autonomous work. A target repo is activated only through explicit harness commands.

## Install the harness capability

```bash
localsetup install --packs harness --tools codex --yes
```

This installs `ls-codex-heartbeat`, `ls-cron-orchestrator`, and `ls-workflow-codex-heartbeat` into the managed Localsetup package library. Normal Localsetup install behavior remains user-initiated.

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

Disable without removing history:

```bash
localsetup harness codex-heartbeat disable
```

`disable` flips config back to disabled and disables the heartbeat cron task. It does not delete historical artifacts.

## Runtime artifacts

Runtime state stays in the target repo under:

```text
state/codex-heartbeat/
```

Each run starts under `runs/<run-id>.staged`. The harness writes `manifest.json`, `heartbeat-result.json`, and `command-log.json`, validates artifact hashes, then atomically promotes the staged directory to `runs/<run-id>`. A run is not successful until that validation and promotion finish.

Pointers stay relative to the state directory:

- `active.json` tracks a currently staged run.
- `latest.json` points to the most recently promoted run and records the manifest hash.
- `heartbeat.lock` prevents concurrent runs.

Interrupted staged runs are preserved as recovered failures before a fresh run starts.

## Command and Codex boundary

Hooks and launch commands run in serial order with `shell=False`, explicit argv lists, timeouts, stdout/stderr tails, sidecar JSON logs, PID/process group/session metadata where available, and manifest hashes.

Direct hook policy blocks `git commit`, `git push`, and common destructive executables unless the target config explicitly allows them.

Codex execution is additionally constrained by the configured Codex command and the normal Codex sandbox and approval settings. The heartbeat harness records and gates execution; it does not replace Codex's sandbox or approval model.

## Cron launcher

Cron entries use the registered Localsetup source checkout through the Localsetup Python launcher, for example:

```text
python3 /path/to/localsetup/_localsetup/tools/localsetup_v3.py --repo /path/to/localsetup --target-directory /path/to/target harness codex-heartbeat run --no-agent
```

The command does not hard-code `_localsetup/skills/...` inside the target repo.
