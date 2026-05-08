---
status: ACTIVE
version: 2.12
last_updated: "2026-03-09"
---

# Workflow quick reference

**Purpose:** Fast lookup for workflow IDs, names, aliases, and primary skills/docs. Use this with [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md); do not duplicate full procedures here.

## Workflows (framework-level)

| Workflow ID | Name | Aliases (also known as) | Skill(s) | Primary doc |
|------------|------|-------------------------|----------|-------------|
| `spec-clarify-reverse` | Reverse prompt (spec clarify) | decision tree; reverse prompt | `localsetup-decision-tree-workflow` | [DECISION_TREE_WORKFLOW.md](DECISION_TREE_WORKFLOW.md) |
| `queue-batch-implement` | Queue batch (implement PRDs) | Agent Q queue; process PRDs | `localsetup-agentic-prd-batch` | [AGENTIC_AGENT_Q_PATTERN.md](AGENTIC_AGENT_Q_PATTERN.md) |
| `transport-handoff` | Agent handoff (mail/file_drop) | Agent Q bidirectional | `localsetup-agentq-transport`; `localsetup-mail-protocol-control` (strict mail) | [AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](AGENTIC_AGENT_TO_AGENT_PROTOCOL.md) |
| `umbrella-run` | Umbrella run (multi-phase) | umbrella workflow | `localsetup-agentic-umbrella-queue` | [AGENTIC_UMBRELLA_WORKFLOWS.md](AGENTIC_UMBRELLA_WORKFLOWS.md) |
| `ops-guarded` | Guarded ops (sudo/HITL) | lazy admin; manual execution | `localsetup-framework-compliance` (tmux ops requires `localsetup-tmux-shared-session-workflow`) | [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) |
| `ops-tmux-session` | Tmux ops session | tmux shared session | `localsetup-tmux-shared-session-workflow` | [ops/tmux-ops-remote.md](ops/tmux-ops-remote.md) |
| `audit-framework` | Framework audit | run audit | `localsetup-framework-audit` | [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) |
| `audit-markdown-references` | Markdown reference audit | reference audit; link integrity audit | `localsetup-markdown-reference-validator` | [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) |
| `skills-index-refresh` | Skill index refresh + scrub | refresh skills; scrub index | `localsetup-skill-discovery` | [SKILL_DISCOVERY.md](SKILL_DISCOVERY.md) |
| `tmux-terminal-mode` | Tmux terminal mode | tmux terminal mode | (tool) `_localsetup/tools/tmux_terminal_mode` | [TMUX_TERMINAL_MODE.md](TMUX_TERMINAL_MODE.md) |

## Pipelines (pass 1)

| Pipeline ID | Name | Steps (skills) | Notes |
|-------------|------|----------------|-------|
| `pipeline-skill-onboard` | Skill onboarding | `localsetup-skill-vetter` (optional) → `localsetup-skill-importer` → `localsetup-skill-normalizer` → `localsetup-skill-sandbox-tester`; optional `localsetup-framework-audit` | Normalizer = batch/legacy normalization when importer already normalizes on import. |
| `pipeline-pre-publish` | Pre-publish | `localsetup-github-publishing-workflow` → `localsetup-automatic-versioning` → `localsetup-framework-audit` | Release automation in scripts/ directory. |
| `pipeline-pr-feedback-loop` | PR feedback improvement loop | `localsetup-receiving-code-review` → `localsetup-tdd-guide` (or `localsetup-test-runner`) → `localsetup-pr-reviewer` | Turn review comments into changes + tests + second automated review. |
| `pipeline-git-repair-hygiene` | Git repair and hygiene | `localsetup-unfuck-my-git-state` → `localsetup-git-workflows` → `localsetup-framework-compliance` | Recover broken git state, then harden workflow with compliance checklist. |
| `pipeline-server-triage-patch` | Server triage and patch | `localsetup-system-info` → `localsetup-linux-service-triage` → `localsetup-linux-patcher` | Ops-only: capture baseline, triage services, then patch hosts/containers with PHC. |
| `pipeline-repo-polish` | Repo polish (docs + scripts) | `localsetup-script-and-docs-quality` → `localsetup-humanizer` → `localsetup-github-publishing-workflow` | Make a repo presentable before sharing, even without full public release. |

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

- `localsetup-npm-management` — Nginx Proxy Manager hosts and routing.
- `localsetup-cloudflare-dns` — DNS records and zone surveys.
- `localsetup-mail-protocol-control` — Full SMTP/IMAP mailbox control (outside strict Agent Q handoff).
- `localsetup-linux-service-triage` — Service diagnostics.
- `localsetup-linux-patcher` — Server patching and Docker updates.

## Publish workflow pointer

| Workflow ID | Name | Aliases | Skill(s) | Note |
|------------|------|---------|----------|------|
| `publish` | Publish workflow | publish; version bump; release | `localsetup-publish-workflow` | Procedure in `docs/WORKFLOW_INDEX.md` and `scripts/publish`. |
