---
status: ACTIVE
version: 3.4
---

# Workflow and module registry (Localsetup v3)

This page is generated from `_localsetup/workflows/*/workflow.yaml`.

For the framework rules, see [WORKFLOW_STANDARD.md](WORKFLOW_STANDARD.md).

## Core

| Name | Description | When to use | Impact review |
|------|-------------|-------------|---------------|
| Master rule / context | Always-loaded framework context | Always | No |
| Skills index | List of capability skills and when to use | When discovering which skill to load | No |

## Workflows

| Workflow ID | Package | Name | Description | Aliases | Required skills | Primary docs/tools |
|-------------|---------|------|-------------|---------|-----------------|--------------------|
| `audit-framework` | `ls-workflow-audit-framework` | Audit Framework | Run framework audit workflow with explicit report path and summarized findings. | run audit; framework audit | `ls-framework-audit` | [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md); [DOCUMENT_LIFECYCLE_MANAGEMENT.md](DOCUMENT_LIFECYCLE_MANAGEMENT.md); `_localsetup/skills/ls-framework-audit/scripts/run_framework_audit.py` |
| `audit-markdown-references` | `ls-workflow-audit-markdown-references` | Audit Markdown References | Validate markdown references and anchors across configured documentation targets. | reference audit; link integrity audit | `ls-markdown-reference-validator` | [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md); [SKILL_VALIDATION_PATTERNS.md](SKILL_VALIDATION_PATTERNS.md); `_localsetup/skills/ls-markdown-reference-validator/scripts/markdown_reference_audit.py` |
| `codex-heartbeat` | `ls-workflow-codex-heartbeat` | Codex Heartbeat | Initialize, activate, run, inspect, and disable the opt-in Codex heartbeat harness with transaction evidence and cron manifest validation. | codex heartbeat; heartbeat harness; harness heartbeat | `ls-codex-heartbeat`; `ls-cron-orchestrator`; `ls-framework-compliance` | [HARNESS_AUTOMATION.md](HARNESS_AUTOMATION.md); [SKILL.md](../../_localsetup/skills/ls-codex-heartbeat/SKILL.md); [transactions.md](../../_localsetup/skills/ls-codex-heartbeat/references/transactions.md); `_localsetup/skills/ls-codex-heartbeat/scripts/codex_heartbeat.py`; `_localsetup/skills/ls-cron-orchestrator/scripts/cron_ctl.py` |
| `documentation-alignment` | `ls-workflow-documentation-alignment` | Documentation Alignment | Run automated repo documentation alignment with source-truth scouting, current-doc research, generated artifacts, CI checks, and final review. | docs alignment; documentation sync; repo docs audit | `ls-documentation-alignment`; `ls-docs-organization`; `ls-markdown-reference-validator`; `ls-script-and-docs-quality`; `ls-test-runner` | [SKILL.md](../../_localsetup/skills/ls-documentation-alignment/SKILL.md); [OUTPUT_AND_DOC_GENERATION.md](OUTPUT_AND_DOC_GENERATION.md); [DOCUMENT_LIFECYCLE_MANAGEMENT.md](DOCUMENT_LIFECYCLE_MANAGEMENT.md); `_localsetup/tools/docs_alignment.py`; `_localsetup/tools/generate_docs_artifacts.py` |
| `ops-guarded` | `ls-workflow-ops-guarded` | Ops Guarded | Apply guarded operations protocol for risky commands with explicit checkpoints. | lazy admin; manual execution | `ls-framework-compliance` | [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) |
| `ops-tmux-session` | `ls-workflow-ops-tmux-session` | Ops Tmux Session | Run guarded operations through managed tmux sessions with explicit run tracking. | tmux shared session | n/a | [tmux-ops-managed.md](ops/tmux-ops-managed.md); [tmux-ops-remote.md](ops/tmux-ops-remote.md); `_localsetup/tools/tmux_ops` |
| `pipeline-git-repair-hygiene` | `ls-workflow-pipeline-git-repair-hygiene` | Pipeline Git Repair Hygiene | Recover Git state issues and enforce workflow hygiene checks. | git repair pipeline | `ls-unfuck-my-git-state`; `ls-git-workflows`; `ls-framework-compliance` | [WORKFLOW_QUICK_REF.md](WORKFLOW_QUICK_REF.md); [GIT_TRACEABILITY.md](GIT_TRACEABILITY.md) |
| `pipeline-pr-feedback-loop` | `ls-workflow-pipeline-pr-feedback-loop` | Pipeline PR Feedback Loop | Turn PR feedback into fixes, tests, and follow-up review. | pr feedback pipeline | `ls-receiving-code-review`; `ls-tdd-guide`; `ls-pr-reviewer` | [WORKFLOW_QUICK_REF.md](WORKFLOW_QUICK_REF.md) |
| `pipeline-pre-publish` | `ls-workflow-pipeline-pre-publish` | Pipeline Pre Publish | Run pre-publish checks, version sync, and framework audit before release actions. | pre publish pipeline | `ls-github-publishing-workflow`; `ls-automatic-versioning`; `ls-framework-audit` | [VERSIONING.md](VERSIONING.md); [WORKFLOW_QUICK_REF.md](WORKFLOW_QUICK_REF.md) |
| `pipeline-repo-convert` | `ls-workflow-pipeline-repo-convert` | Pipeline Repo Convert | Convert an existing repo to the current Localsetup v3 framework with backup, blocker, install, and verification gates. | repo convert pipeline; convert repo; localsetup convert | `ls-framework-compliance`; `ls-safety-and-backup`; `ls-git-workflows`; `ls-test-runner` | [REPO_CONVERSION.md](REPO_CONVERSION.md); [MULTI_PLATFORM_INSTALL.md](MULTI_PLATFORM_INSTALL.md); `git` |
| `pipeline-repo-polish` | `ls-workflow-pipeline-repo-polish` | Pipeline Repo Polish | Polish repository docs and scripts for sharing readiness. | repo polish pipeline | `ls-script-and-docs-quality`; `ls-humanizer`; `ls-github-publishing-workflow` | [WORKFLOW_QUICK_REF.md](WORKFLOW_QUICK_REF.md); [README.md](README.md) |
| `pipeline-server-triage-patch` | `ls-workflow-pipeline-server-triage-patch` | Pipeline Server Triage Patch | Capture server baseline, triage issues, and apply patch operations. | server triage patch pipeline | `ls-system-info`; `ls-linux-service-triage`; `ls-linux-patcher` | [WORKFLOW_QUICK_REF.md](WORKFLOW_QUICK_REF.md); [tmux-ops-managed.md](ops/tmux-ops-managed.md) |
| `pipeline-skill-onboard` | `ls-workflow-pipeline-skill-onboard` | Pipeline Skill Onboard | Run the skill onboarding pipeline from vetting through sandbox testing. | skill onboarding pipeline | `ls-skill-vetter`; `ls-skill-importer`; `ls-skill-normalizer`; `ls-skill-sandbox-tester` | [WORKFLOW_QUICK_REF.md](WORKFLOW_QUICK_REF.md); [SKILL_IMPORTING.md](SKILL_IMPORTING.md) |
| `queue-batch-implement` | `ls-workflow-queue-batch-implement` | Queue Batch Implement | Process queued PRD tasks in batch with status tracking and outcome reporting. | Agent Q queue; process PRDs | n/a | [AGENTIC_AGENT_Q_PATTERN.md](AGENTIC_AGENT_Q_PATTERN.md); [PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md) |
| `skills-index-refresh` | `ls-workflow-skills-index-refresh` | Skills Index Refresh | Refresh and scrub the public skill index in the required sequence. | refresh skills; scrub index | `ls-skill-discovery` | [SKILL_DISCOVERY.md](SKILL_DISCOVERY.md); [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) |
| `spec-clarify-reverse` | `ls-workflow-spec-clarify-reverse` | Reverse Prompt Spec Clarify | Run reverse-prompt spec clarification with one question per turn and bounded choices. | decision tree; reverse prompt | n/a | [DECISION_TREE_WORKFLOW.md](DECISION_TREE_WORKFLOW.md); [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) |
| `tmux-terminal-mode` | `ls-workflow-tmux-terminal-mode` | Tmux Terminal Mode | Manage tmux terminal mode enable, disable, and status behavior. | tmux terminal mode; always-on tmux | n/a | [TMUX_TERMINAL_MODE.md](TMUX_TERMINAL_MODE.md); [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md); `_localsetup/tools/tmux_terminal_mode` |
| `transport-handoff` | `ls-workflow-transport-handoff` | Transport Handoff | Handle sealed Agent Q handoff payload transport over file_drop or mail adapters. | Agent Q bidirectional | `ls-agentq-transport`; `ls-mail-protocol-control` | [AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](AGENTIC_AGENT_TO_AGENT_PROTOCOL.md); [AGENTIC_AGENT_Q_SCENARIOS.md](AGENTIC_AGENT_Q_SCENARIOS.md); [AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md](AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md); `_localsetup/tools/agentq_transport_client/agentq_cli.py` |
| `umbrella-run` | `ls-workflow-umbrella-run` | Umbrella Run | Execute a named multi-phase umbrella workflow with explicit pre-human-confirmation gates. | umbrella workflow | n/a | [AGENTIC_UMBRELLA_WORKFLOWS.md](AGENTIC_UMBRELLA_WORKFLOWS.md); [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) |

## Usage

- Agents load the workflow package when a user invokes a workflow ID, package name, or alias.
- Workflow packages install into the managed skill library because every package includes a valid `SKILL.md`.
- Required skills listed in `workflow.yaml` are automatically selected when a workflow's pack is selected.
- Historical publish workflow pointers are retired; use `ls-github-publishing-workflow` plus `ls-automatic-versioning`.
