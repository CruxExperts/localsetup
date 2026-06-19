---
status: ACTIVE
version: 4.1
owner_package: generate-docs
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 250760d598afdba4b587126bb28b5f7a9ae78837b60b35891f06647c069cd425
  emitter: generate-docs
framework_version: 4.1.2
source_commit: 967490063d76a8de22164ba95ad093c747c72900
artifact_sha256: 0349628834db69dbd87364c3f2fc20ef1ba9d670b5ad592ee2813198aaa8840b
---
# Workflow quick reference

This page is generated from `_localsetup/workflows/*/workflow.yaml`.

## Workflows

| Workflow ID | Name | Aliases | Package | Required skills |
|------------|------|---------|---------|-----------------|
| `audit-framework` | Audit Framework | run audit; framework audit | `ls-workflow-audit-framework` | `ls-framework-audit` |
| `audit-markdown-references` | Audit Markdown References | reference audit; link integrity audit | `ls-workflow-audit-markdown-references` | `ls-markdown-reference-validator` |
| `codex-heartbeat` | Codex Heartbeat | codex heartbeat; heartbeat harness; harness heartbeat | `ls-workflow-codex-heartbeat` | `ls-codex-heartbeat`; `ls-cron-orchestrator`; `ls-framework-compliance` |
| `context-index-query` | Context Index Query | query context index; context search | `ls-workflow-context-index-query` | `ls-context-index` |
| `context-index-refresh` | Context Index Refresh | context refresh; refresh context index | `ls-workflow-context-index-refresh` | `ls-context-index` |
| `documentation-alignment` | Documentation Alignment | docs alignment; documentation sync; repo docs audit | `ls-workflow-documentation-alignment` | `ls-documentation-alignment`; `ls-docs-organization`; `ls-markdown-reference-validator`; `ls-script-and-docs-quality`; `ls-test-runner` |
| `ops-guarded` | Ops Guarded | lazy admin; manual execution | `ls-workflow-ops-guarded` | `ls-framework-compliance` |
| `ops-tmux-session` | Ops Tmux Session | tmux shared session | `ls-workflow-ops-tmux-session` | n/a |
| `pipeline-git-repair-hygiene` | Pipeline Git Repair Hygiene | git repair pipeline | `ls-workflow-pipeline-git-repair-hygiene` | `ls-unfuck-my-git-state`; `ls-git-workflows`; `ls-framework-compliance` |
| `pipeline-pr-feedback-loop` | Pipeline PR Feedback Loop | pr feedback pipeline | `ls-workflow-pipeline-pr-feedback-loop` | `ls-receiving-code-review`; `ls-tdd-guide`; `ls-pr-reviewer` |
| `pipeline-pre-publish` | Pipeline Pre Publish | pre publish pipeline | `ls-workflow-pipeline-pre-publish` | `ls-github-publishing-workflow`; `ls-automatic-versioning`; `ls-framework-audit` |
| `pipeline-repo-convert` | Pipeline Repo Convert | repo convert pipeline; convert repo; localsetup convert | `ls-workflow-pipeline-repo-convert` | `ls-framework-compliance`; `ls-safety-and-backup`; `ls-git-workflows`; `ls-test-runner` |
| `pipeline-repo-polish` | Pipeline Repo Polish | repo polish pipeline | `ls-workflow-pipeline-repo-polish` | `ls-script-and-docs-quality`; `ls-humanizer`; `ls-github-publishing-workflow` |
| `pipeline-server-triage-patch` | Pipeline Server Triage Patch | server triage patch pipeline | `ls-workflow-pipeline-server-triage-patch` | `ls-system-info`; `ls-linux-service-triage`; `ls-linux-patcher` |
| `pipeline-skill-onboard` | Pipeline Skill Onboard | skill onboarding pipeline | `ls-workflow-pipeline-skill-onboard` | `ls-skill-vetter`; `ls-skill-importer`; `ls-skill-normalizer`; `ls-skill-sandbox-tester` |
| `planning-critic-loop` | Planning Critic Loop | planning critic loop; planning agent critic; critic reviewed plan | `ls-workflow-planning-critic-loop` | n/a |
| `queue-batch-implement` | Queue Batch Implement | Agent Q queue; process PRDs | `ls-workflow-queue-batch-implement` | n/a |
| `repo-finalizer` | Repo Finalizer | repo finalizer; finalizer harness; finalization checkpoint | `ls-workflow-repo-finalizer` | `ls-framework-compliance`; `ls-git-workflows` |
| `skills-index-refresh` | Skills Index Refresh | refresh skills; scrub index | `ls-workflow-skills-index-refresh` | `ls-skill-discovery` |
| `spec-clarify-reverse` | Reverse Prompt Spec Clarify | decision tree; reverse prompt | `ls-workflow-spec-clarify-reverse` | n/a |
| `tmux-terminal-mode` | Tmux Terminal Mode | tmux terminal mode; always-on tmux | `ls-workflow-tmux-terminal-mode` | n/a |
| `transport-handoff` | Transport Handoff | Agent Q bidirectional | `ls-workflow-transport-handoff` | `ls-agentq-transport`; `ls-mail-protocol-control` |
| `umbrella-run` | Umbrella Run | umbrella workflow | `ls-workflow-umbrella-run` | n/a |

## Common Phrases

- "run audit" -> `audit-framework`
- "framework audit" -> `audit-framework`
- "reference audit" -> `audit-markdown-references`
- "link integrity audit" -> `audit-markdown-references`
- "codex heartbeat" -> `codex-heartbeat`
- "heartbeat harness" -> `codex-heartbeat`
- "harness heartbeat" -> `codex-heartbeat`
- "query context index" -> `context-index-query`
- "context search" -> `context-index-query`
- "context refresh" -> `context-index-refresh`
- "refresh context index" -> `context-index-refresh`
- "docs alignment" -> `documentation-alignment`
- "documentation sync" -> `documentation-alignment`
- "repo docs audit" -> `documentation-alignment`
- "lazy admin" -> `ops-guarded`
- "manual execution" -> `ops-guarded`
- "tmux shared session" -> `ops-tmux-session`
- "git repair pipeline" -> `pipeline-git-repair-hygiene`
- "pr feedback pipeline" -> `pipeline-pr-feedback-loop`
- "pre publish pipeline" -> `pipeline-pre-publish`
- "repo convert pipeline" -> `pipeline-repo-convert`
- "convert repo" -> `pipeline-repo-convert`
- "localsetup convert" -> `pipeline-repo-convert`
- "repo polish pipeline" -> `pipeline-repo-polish`
- "server triage patch pipeline" -> `pipeline-server-triage-patch`
- "skill onboarding pipeline" -> `pipeline-skill-onboard`
- "planning critic loop" -> `planning-critic-loop`
- "planning agent critic" -> `planning-critic-loop`
- "critic reviewed plan" -> `planning-critic-loop`
- "Agent Q queue" -> `queue-batch-implement`
- "process PRDs" -> `queue-batch-implement`
- "repo finalizer" -> `repo-finalizer`
- "finalizer harness" -> `repo-finalizer`
- "finalization checkpoint" -> `repo-finalizer`
- "refresh skills" -> `skills-index-refresh`
- "scrub index" -> `skills-index-refresh`
- "decision tree" -> `spec-clarify-reverse`
- "reverse prompt" -> `spec-clarify-reverse`
- "tmux terminal mode" -> `tmux-terminal-mode`
- "always-on tmux" -> `tmux-terminal-mode`
- "Agent Q bidirectional" -> `transport-handoff`
- "umbrella workflow" -> `umbrella-run`
