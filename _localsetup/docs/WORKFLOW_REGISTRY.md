---
status: ACTIVE
version: 3.0
---

# Workflow and module registry (Localsetup v3)

**Purpose:** Registry of named workflows and when to use them; impact review when required. For the full agentic doc index, see [AGENTIC_DESIGN_INDEX.md](AGENTIC_DESIGN_INDEX.md).

## Core

| Name | Description | When to use | Impact review |
|------|-------------|-------------|---------------|
| Master rule / context | Always-loaded framework context | Always | No |
| Skills index | List of skills and when to use | When discovering which skill to load | No |

**Doc map:** Master rule and skills table live per platform (e.g. `.cursor/rules/ls-context.mdc`, templates under `_localsetup/templates/`). Generated catalog: [SKILLS.md](SKILLS.md).

## Workflows

| Workflow ID | Name | Description | When to use | Impact review | Aliases | Canonical doc / skill |
|-------------|------|-------------|-------------|---------------|---------|------------------------|
| `spec-clarify-reverse` | Reverse prompt (spec clarify) | One Q per turn, 4 options A-D, preferred + rationale | User says "decision tree" or "reverse prompt" | No | decision tree; reverse prompt | [DECISION_TREE_WORKFLOW.md](DECISION_TREE_WORKFLOW.md); skill `ls-decision-tree-workflow` |
| `queue-batch-implement` | Queue batch (implement PRDs) | Process specs in `.agent/queue/` (or structured `in/`); implement, status, outcome | User says "process PRDs" or "run batch from PRD folder" | Yes if destructive | Agent Q queue; process PRDs | [AGENTIC_AGENT_Q_PATTERN.md](AGENTIC_AGENT_Q_PATTERN.md), [PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md); skill `ls-agentic-prd-batch` |
| `transport-handoff` | Agent handoff (mail/file_drop) | Transport adapters (mail/file_drop) pull sealed payloads into inbox/in; outbound ack/artifact after pre-ship gate | Agent-to-agent PRD exchange over shared folder or mail | Yes if destructive ship | Agent Q bidirectional | [AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](AGENTIC_AGENT_TO_AGENT_PROTOCOL.md), [AGENTIC_AGENT_Q_SCENARIOS.md](AGENTIC_AGENT_Q_SCENARIOS.md), [AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md](AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md); skills `ls-agentq-transport`, `ls-mail-protocol-control` (strict mail: `preencrypted_openpgp_armored`); CLI `_localsetup/tools/agentq_transport_client/agentq_cli.py` |
| `umbrella-run` | Umbrella run (multi-phase) | Multi-phase single kickoff; named workflows; PHC gates | User invokes by name (e.g. "execute umbrella workflow X") | Yes for big/destructive | umbrella workflow | [AGENTIC_UMBRELLA_WORKFLOWS.md](AGENTIC_UMBRELLA_WORKFLOWS.md); skill `ls-agentic-umbrella-queue` |
| `ops-guarded` | Guarded ops (sudo/HITL) | Human-in-the-loop; info-gather before destructive; checkpoints | Sudo, confirmation, manual steps | No (protocol is guardrail) | lazy admin; manual execution | Skill `ls-framework-compliance` (pre-task, destructive gates); tmux ops still require `ls-tmux-shared-session-workflow` |
| `ops-tmux-session` | Tmux ops session | Server ops in managed tmux sessions via `tmux_ops` (`pick`, `probe`, `run`, `status`, `cancel`); captured logs and explicit run IDs; REMOTE_TMUX_HOST for remote/VMs | Server commands, deployments, tmux, human-in-the-loop | No (skill defines gate) | tmux shared session | [ops/tmux-ops-remote.md](ops/tmux-ops-remote.md); skill `ls-tmux-shared-session-workflow`; tool `_localsetup/tools/tmux_ops` |
| `audit-framework` | Framework audit | Doc/link/skill matrix/version checks; **output path required** for report file | User says "run audit", "run framework audit", or before release | No | run audit | Skill `ls-framework-audit`; entrypoint `python _localsetup/skills/ls-framework-audit/scripts/run_framework_audit.py --output /path/to/report.md` (or `LOCALSETUP_AUDIT_OUTPUT`). Smoke list: `_localsetup/tests/skill_smoke_commands.yaml` |
| `audit-markdown-references` | Markdown reference audit | Validate markdown local references/anchors across configured repo/global Kilo targets; schedule-safe output | Periodic docs/skills integrity checks or when user says "validate markdown references" | No | reference audit; link integrity audit | Skill `ls-markdown-reference-validator`; entrypoint `python _localsetup/skills/ls-markdown-reference-validator/scripts/markdown_reference_audit.py --force --reason manual`; config `_localsetup/skills/ls-markdown-reference-validator/markdown_reference_audit.yaml` |
| `skills-index-refresh` | Skill index refresh + scrub | Refresh index then scrub (mandatory sequence) | User says "refresh skills", "update public skill index", "refresh and scrub", or "scrub the index" | No | refresh skills; scrub index | [SKILL_DISCOVERY.md](SKILL_DISCOVERY.md) (refresh + scrub block); skill `ls-skill-discovery` |
| `tmux-terminal-mode` | Tmux terminal mode | Enable/disable/status via `_localsetup/tools/tmux_terminal_mode`; ide or shell mode; injects agent ops rule | User says "enable tmux mode", "tmux terminal mode", "disable tmux mode", "always-on tmux", or setting up ops machine | No | tmux terminal mode; always-on tmux | [TMUX_TERMINAL_MODE.md](TMUX_TERMINAL_MODE.md); tool `_localsetup/tools/tmux_terminal_mode` |

Release and publish workflows are documented in `docs/WORKFLOW_INDEX.md` and `docs/MAINTENANCE_WORKFLOW.md`.

## Usage

- **Agents:** For workflows marked impact review, present impact summary and get user confirmation before proceeding.
- **Skills:** Load the matching skill when the task matches (see Canonical doc / skill column above).
- **Tmux/sudo:** Pick a managed session, show `attach_command`, probe (`ready`, `password_required`, or `failed`), then run every command with `tmux_ops run -t SESSION -- CMD`. Use returned `run_id`, `tail`, `log_path`, and `status`; timeouts mean the run is still active. Continue watching with `status --wait`, and interrupt only with `cancel --run-id`. When `REMOTE_TMUX_HOST` is set, the wrapper runs over SSH. Re-prompt only when probe returns `password_required`.
- **Public skill index:** Run refresh then scrub then scrub --fix in order; see [SKILL_DISCOVERY.md](SKILL_DISCOVERY.md). Scrub also applies when index refresh is triggered through skill-discovery.
- **Tmux-default terminal mode:** `_localsetup/tools/tmux_terminal_mode enable [--mode ide|shell] [--session NAME]`, `disable`, or `status`. See [TMUX_TERMINAL_MODE.md](TMUX_TERMINAL_MODE.md).
- **Framework audit:** Do not claim a `--deep` flag unless the audit script documents it; current entrypoint is `run_framework_audit.py` with `--output` or env (see skill `ls-framework-audit`).
- **Non-ACTIVE docs:** For agent-facing docs with `status` not ACTIVE (see [DOCUMENT_LIFECYCLE_MANAGEMENT.md](DOCUMENT_LIFECYCLE_MANAGEMENT.md)), check status before following. Example: [AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md](AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md) is ACTIVE but its Part 19 describes backlog; do not treat Part 19 as shipped behavior.
