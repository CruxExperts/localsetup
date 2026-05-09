---
status: ACTIVE
version: 3.0
last_updated: "2026-03-09"
---

# Workflow quick reference

**Purpose:** Fast lookup for workflow IDs, names, aliases, and primary skills/docs. Use this with [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md); do not duplicate full procedures here.

## Workflows (framework-level)

| Workflow ID | Name | Aliases (also known as) | Skill(s) | Primary doc |
|------------|------|-------------------------|----------|-------------|
| `spec-clarify-reverse` | Reverse prompt (spec clarify) | decision tree; reverse prompt | `ls-decision-tree-workflow` | [DECISION_TREE_WORKFLOW.md](DECISION_TREE_WORKFLOW.md) |
| `queue-batch-implement` | Queue batch (implement PRDs) | Agent Q queue; process PRDs | `ls-agentic-prd-batch` | [AGENTIC_AGENT_Q_PATTERN.md](AGENTIC_AGENT_Q_PATTERN.md) |
| `transport-handoff` | Agent handoff (mail/file_drop) | Agent Q bidirectional | `ls-agentq-transport`; `ls-mail-protocol-control` (strict mail) | [AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](AGENTIC_AGENT_TO_AGENT_PROTOCOL.md) |
| `umbrella-run` | Umbrella run (multi-phase) | umbrella workflow | `ls-agentic-umbrella-queue` | [AGENTIC_UMBRELLA_WORKFLOWS.md](AGENTIC_UMBRELLA_WORKFLOWS.md) |
| `ops-guarded` | Guarded ops (sudo/HITL) | lazy admin; manual execution | `ls-framework-compliance` (tmux ops requires `ls-tmux-shared-session-workflow`) | [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) |
| `ops-tmux-session` | Tmux ops session | tmux shared session | `ls-tmux-shared-session-workflow` | [ops/tmux-ops-remote.md](ops/tmux-ops-remote.md) |
| `audit-framework` | Framework audit | run audit | `ls-framework-audit` | [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) |
| `audit-markdown-references` | Markdown reference audit | reference audit; link integrity audit | `ls-markdown-reference-validator` | [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) |
| `skills-index-refresh` | Skill index refresh + scrub | refresh skills; scrub index | `ls-skill-discovery` | [SKILL_DISCOVERY.md](SKILL_DISCOVERY.md) |
| `tmux-terminal-mode` | Tmux terminal mode | tmux terminal mode | (tool) `_localsetup/tools/tmux_terminal_mode` | [TMUX_TERMINAL_MODE.md](TMUX_TERMINAL_MODE.md) |

## Pipelines (pass 1)

| Pipeline ID | Name | Steps (skills) | Notes |
|-------------|------|----------------|-------|
| `pipeline-skill-onboard` | Skill onboarding | `ls-skill-vetter` (optional) → `ls-skill-importer` → `ls-skill-normalizer` → `ls-skill-sandbox-tester`; optional `ls-framework-audit` | Normalizer = batch/legacy normalization when importer already normalizes on import. |
| `pipeline-pre-publish` | Pre-publish | `ls-github-publishing-workflow` → `ls-automatic-versioning` → `ls-framework-audit` | Release automation in scripts/ directory. |
| `pipeline-pr-feedback-loop` | PR feedback improvement loop | `ls-receiving-code-review` → `ls-tdd-guide` (or `ls-test-runner`) → `ls-pr-reviewer` | Turn review comments into changes + tests + second automated review. |
| `pipeline-git-repair-hygiene` | Git repair and hygiene | `ls-unfuck-my-git-state` → `ls-git-workflows` → `ls-framework-compliance` | Recover broken git state, then harden workflow with compliance checklist. |
| `pipeline-server-triage-patch` | Server triage and patch | `ls-system-info` → `ls-linux-service-triage` → `ls-linux-patcher` | Ops-only: capture baseline, triage services, then patch hosts/containers with PHC. |
| `pipeline-repo-polish` | Repo polish (docs + scripts) | `ls-script-and-docs-quality` → `ls-humanizer` → `ls-github-publishing-workflow` | Make a repo presentable before sharing, even without full public release. |

## Common phrases → Workflow IDs

- "decision tree", "reverse prompt" → `spec-clarify-reverse`
- "process PRDs", "run batch from PRD folder" → `queue-batch-implement`
- "Agent Q bidirectional", "mail/file_drop handoff" → `transport-handoff`
- "umbrella workflow" → `umbrella-run`
- "lazy admin", "manual execution with sudo" → `ops-guarded`
- "tmux shared session" → `ops-tmux-session`
- "run audit", "framework audit" → `audit-framework`
- "refresh skills", "scrub public skill index" → `skills-index-refresh`
- "tmux terminal mode", "always-on tmux" → `tmux-terminal-mode`

## Capabilities without dedicated workflow rows (examples)

These skills are high-value capabilities that usually appear as **steps** inside pipelines or ad-hoc tasks, not as standalone named workflows. Use them via task-skill matching or pipelines.

- `ls-npm-management` — Nginx Proxy Manager hosts and routing.
- `ls-cloudflare-dns` — DNS records and zone surveys.
- `ls-mail-protocol-control` — Full SMTP/IMAP mailbox control (outside strict Agent Q handoff).
- `ls-linux-service-triage` — Service diagnostics.
- `ls-linux-patcher` — Server patching and Docker updates.

## Publish workflow pointer

| Workflow ID | Name | Aliases | Skill(s) | Note |
|------------|------|---------|----------|------|
