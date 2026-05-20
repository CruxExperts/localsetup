---
name: ls-codex-heartbeat
description: "Opt-in Codex heartbeat harness for target repositories: initialize config, run transaction-safe heartbeat checks, preserve artifacts, and wire cron only after explicit activation."
metadata:
  version: "1.0"
compatibility: "Python 3.12+, PyYAML, Localsetup.4 harness CLI."
---

# Codex Heartbeat

Use this skill when a repository needs an explicit, auditable heartbeat harness for periodic Codex-oriented checks.

## Guardrails

- Installing this skill only makes the harness available. It does not create config, cron entries, or autonomous runs.
- Activate per target repo with `localsetup harness codex-heartbeat init` and `enable`.
- Runtime artifacts stay under ignored target-repo `.localsetup/state/codex-heartbeat/`.
- `enable --install-crontab` refuses to install a live crontab unless `--yes` is also passed.
- `run --no-agent` exercises locks, recovery, command logging, staged validation, and atomic promotion without model use.
- Direct hooks block `git commit`, `git push`, and destructive executables unless explicitly allowed.
- Codex model execution is constrained by the configured agent profile, launcher mode, sandbox, and Codex client settings. The profile may pin a model, but the framework default leaves the model configurable. This harness records and gates execution; it is not a sandbox replacement.

## Rule ownership

This skill owns heartbeat harness behavior. `HARNESS_AUTOMATION.md` is the public reference for the same guardrails; changes to activation, artifacts, transaction handling, or cron wiring belong here first.

- Heartbeat is opt-in per target repo.
- Cron activation is delegated to explicit harness commands and should be coordinated with `ls-cron-orchestrator` when broader scheduling is involved.
- Runtime evidence stays in ignored target state, not public framework docs.

## Commands

```bash
localsetup harness codex-heartbeat plan
localsetup harness codex-heartbeat init
localsetup harness codex-heartbeat enable
localsetup harness codex-heartbeat status
localsetup harness codex-heartbeat run --no-agent
localsetup harness codex-heartbeat disable
```

Standalone runtime script:

```bash
python3 _localsetup/skills/ls-codex-heartbeat/scripts/codex_heartbeat.py --target-root . --no-agent
```

## References

- `references/config.md`
- `references/artifacts.md`
- `references/recovery.md`
- `references/command-logging.md`
- `references/process-control.md`
- `references/transactions.md`
