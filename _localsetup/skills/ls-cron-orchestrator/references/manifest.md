# Cron Manifest Reference

`cron_ctl.py` and `run_trigger.py` read the same YAML manifest and validate it before listing, installing, or running tasks. Validation errors include the manifest path location, such as `tasks[0].command`, so agents can fix the exact field.

## Schema

```yaml
triggers:
  midnight-utc:
    schedule: "0 0 * * *"
  after-boot:
    on_boot_delay_minutes: 5
tasks:
  - id: snapshot-daily
    trigger: midnight-utc
    sequence_order: 1
    command:
      - python3
      - _localsetup/skills/ls-system-info/scripts/system_snapshot.py
      - --output-basename
      - reports/system-snapshots/daily
    enabled: true
    timeout_seconds: 3600
```

## Validation Rules

- `triggers` must be a non-empty mapping.
- Trigger names and task ids may contain letters, numbers, `.`, `_`, `:`, `@`, `+`, and `-`.
- A trigger must define exactly one of `schedule` or `on_boot_delay_minutes`.
- `schedule` must contain exactly five cron fields.
- `on_boot_delay_minutes` must be an integer from 0 to 1440.
- `tasks` must be a list when present.
- Each task must include `id`, `trigger`, `sequence_order`, and `command`.
- `enabled`, when present, must be boolean.
- `timeout_seconds`, when present, must be an integer from 1 to 86400.

## Command Model

Commands are executed with `shell=False`. Prefer an argv list so each argument is explicit and no shell parsing is needed.

String commands are accepted for simple cases, but they are parsed with `shlex.split` and rejected when they contain shell-only operators such as `&&`, `||`, `;`, `|`, redirects, backticks, `$(`, or `${`. Use an argv list for literal arguments that contain shell-looking characters.

Generated cron lines quote every runner argument with `shlex.join` and escape `%`, which cron treats as a newline marker in command fields. On-boot delays are passed to `run_trigger.py --delay-seconds` instead of interpolating a `sleep ... &&` shell fragment.

## Runner Logs

Cron hosts do not always have an MTA or other stdout/stderr sink. Use
`cron_ctl.py install --log-dir PATH` to add `run_trigger.py --log-dir PATH` to
generated cron lines. When enabled, `run_trigger.py` appends timestamped
`runner_start`, `task_start`, `task_exit`, timeout/error, and `runner_exit`
records to `PATH/<trigger>.log`. Task exit records include bounded stdout and
stderr tails so operators can diagnose child process failures without relying
on cron mail.
