# Arbiter Filesystem Queue Overview

`ls-arbiter` provides an agent-side Python helper for creating and reading Arbiter Zebu decision plans. The helper is intentionally local and file-based: it writes markdown plans into an Arbiter queue and reads completed plan metadata after a reviewer or bot records answers.

## Lifecycle

```text
agent pushes plan JSON
  -> scripts/arbiter_cli.py writes ~/.arbiter/queue/pending/<plan>.md
  -> Arbiter Zebu bot or human reviewer reads the pending plan
  -> reviewer records answers and marks the plan complete
  -> completed answers are available through get, await, or heartbeat polling
```

The CLI does not send chat messages, run the Arbiter Zebu bot, or perform external notification delivery. Notification files under `~/.arbiter/queue/notify/` are optional coordination inputs for the agent heartbeat.

## Queue Layout

| Path | Meaning |
|---|---|
| `~/.arbiter/queue/pending/` | Plans waiting for review |
| `~/.arbiter/queue/completed/` | Plans that have answers |
| `~/.arbiter/queue/notify/` | Session notification markers consumed by heartbeat logic |

Use `--queue-dir <path>` on any subcommand to test against a temporary queue without touching the user queue.

## Generated Plan Shape

The generated markdown file has YAML frontmatter with plan metadata and a `decisions` list. The body repeats the same decisions in a reviewer-friendly format.

Important frontmatter fields:

| Field | Meaning |
|---|---|
| `planId` / `id` | Unique plan identifier |
| `tag` | Project or topic lookup key |
| `status` | `pending` or `completed` |
| `total`, `answered`, `remaining` | Decision counts |
| `decisions[].answer` | Completed answer value |

`status` and `get` read the frontmatter first. If an external reviewer uses a different answer format, normalize it back into the frontmatter before relying on the bundled CLI.

## Minimal Completion Convention

A completed plan should either be moved into `completed/` or have `status: completed` in frontmatter. Each answered decision should include:

```yaml
status: answered
answer: selected-option-key
answered_at: "2026-05-09T18:00:00Z"
```

When all decisions have answers, `get` returns a JSON `answers` object keyed by decision ID.

## Heartbeat Reference

Agent heartbeat or session-resume logic should check `notify/` for local notification files, then call:

```bash
python3 scripts/arbiter_cli.py get <plan-id>
```

If no notification file is present, the agent may still poll with `status --tag <tag>` for known blockers.
