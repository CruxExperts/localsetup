---
name: ls-codex-heartbeat
description: "Opt-in agent heartbeat harness for target repositories: initialize config, run transaction-safe checks, preserve artifacts, and wire cron only after explicit activation."
metadata:
  version: "1.0"
compatibility: "Python 3.12+, PyYAML, LocalSetup.4 harness CLI."
---

# Agent Heartbeat

Use this skill when a repository needs an explicit, auditable heartbeat harness for periodic checks run by a configured agent CLI. The runtime is client-neutral: each profile supplies its own executable argv, prompt transport, and launcher mode.

## Guardrails

- Installing this skill only makes the harness available. It does not create config, cron entries, or autonomous runs.
- Activate per target repo with `localsetup harness codex-heartbeat init` and `enable`.
- Runtime artifacts stay under ignored target-repo `.localsetup/state/codex-heartbeat/`.
- `enable --install-crontab` refuses to install a live crontab unless `--yes` is also passed.
- `run --no-agent` exercises lock acquisition, recovery, command logging, staged validation, and atomic promotion without launching the configured agent.
- A run acquires `heartbeat.lock` before inspecting or changing active and staged state. It reclaims only a same-host lock whose owner PID is absent and whose age meets `heartbeat.stale_after_seconds`, then unlinks that held stale pathname and retries exclusive acquisition. Ambiguous locks remain locked for manual review.
- Direct hooks reject `git commit`, `git push`, and blocked destructive executables unless their specific policy switches are enabled; Git global options are parsed before the subcommand check.
- Every executed or policy-blocked command receives a sidecar. Promotion validates hashes for the result, command log, and every logged sidecar.
- Agent profiles record execution; they are not a sandbox replacement.

## Rule ownership

This skill owns heartbeat harness behavior. `HARNESS_AUTOMATION.md` is the public reference for the same guardrails; changes to activation, artifacts, transaction handling, or cron wiring belong here first.

- Heartbeat is opt-in per target repo.
- Cron activation is delegated to explicit harness commands and should be coordinated with `ls-cron-orchestrator` when broader scheduling is involved.
- Runtime evidence stays in ignored target state, not public framework docs.

## Activation and evidence workflow

Use `ls-framework-compliance` for repository checks and `ls-cron-orchestrator`
for scheduling coordination. Preserve the explicit activation gates throughout
this lifecycle:

1. Inspect the target paths, configuration, cron manifest, and launcher with `plan`.
2. Use `init` to create `HEARTBEAT.md` and configuration with heartbeat disabled.
3. Use `enable` to update the heartbeat configuration and cron manifest while
   preserving unrelated tasks; retain the live-crontab confirmation gate above.
4. Validate a run with `--no-agent` when appropriate. Success requires validated
   staged artifacts and atomic promotion, as defined in `references/transactions.md`.
5. Inspect configuration, cron, lock, latest pointer, and run evidence with `status`.
6. Use `disable` to stop future heartbeat runs without deleting historical artifacts.

Record activation, validation, and artifact locations in the run ledger.

## Commands

```bash
localsetup harness codex-heartbeat plan
localsetup harness codex-heartbeat init
localsetup harness codex-heartbeat enable
localsetup harness codex-heartbeat status
localsetup harness codex-heartbeat budget
localsetup harness codex-heartbeat run --no-agent
localsetup harness codex-heartbeat disable
```

`budget` is read-only. It reports policy, summary, and task reservations from `heartbeat.task_queue_path` when configured; it does not spawn agents or enforce scheduling.

Standalone runtime script:

```bash
python3 ls/skills/ls-codex-heartbeat/scripts/codex_heartbeat.py --target-root . --no-agent
```

## References

- `references/config.md`
- `references/artifacts.md`
- `references/recovery.md`
- `references/command-logging.md`
- `references/process-control.md`
- `references/transactions.md`
