---
name: ls-agentic-prd-batch
description: "Agentic PRD batch: process ready PRDs from .agent/queue/**, configured PRD folders such as prds/**, or explicit *.prd.md files; implement per spec; update status; write an Outcome block; reference PRD schema + external-agent guide."
metadata:
  version: "1.3"
compatibility: "Requires Python 3.10+ and framework deps for transport-client stamp/ship helpers; requires gpg on PATH only for key generation or strict GPG transport flows."
---

# Agentic PRD batch

When the user says **process PRDs**, **run batch from PRD folder**, **process the queue**, or similar, or when editing queued/configured PRD files with intent to implement:

1. **Locate specs:** Look for PRD/spec files in the user-specified or repo-configured PRD location: queue roots such as `.agent/queue/`, structured queue intake such as `.agent/queue/in/`, configured folders such as `prds/`, or explicit `*.prd.md` paths. Exclude README, INDEX, SPEC-TEMPLATE. Filter by front matter `status == ready` (or `in-progress` if resuming). Sort by priority (high first), then filename date (oldest first). **Version mismatch:** If a spec has `localsetup_framework_version` and it differs from repo root VERSION, surface a warning per protocol; do not silently ignore.
2. **Implement per spec:** Load each spec; follow Implementation steps and Acceptance criteria; satisfy Verification plan and Rollback plan. Use PRD schema and [_localsetup/docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](../../docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md) for format and outcome template.
3. **Update status:** Set spec `status: in-progress` when starting; set `status: done` (or `blocked`) when finished. Update queue INDEX if present.
4. **Write outcome:** Append a durable `## Outcome` block per spec with branch, commit SHA, files changed, verification, rollback command, and any agent-to-agent transport fields required by PRD_SCHEMA_EXTERNAL_AGENT_GUIDE. Do not invent alternate outcome keys unless the active PRD schema explicitly defines them.
5. **Clean-tree invariant:** Before marking a spec done, ensure repo is clean (no modified tracked files except intended commits; untracked queue specs allowed). Commit or revert as needed.
6. **External confirmation:** If spec front matter includes `external_confirmation: acknowledged` or `impact_review: confirmed_by: external_agent`, agent may skip human impact confirmation; otherwise follow guardrails (impact summary + user confirmation for big/destructive changes).

## Reference

- [_localsetup/docs/AGENTIC_AGENT_Q_PATTERN.md](../../docs/AGENTIC_AGENT_Q_PATTERN.md)  - queue pattern (flat and structured layout).
- [_localsetup/docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](../../docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md)  - spec format, front matter, outcome template, clarification protocol.
- [_localsetup/docs/AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](../../docs/AGENTIC_AGENT_TO_AGENT_PROTOCOL.md)  - agent-to-agent handoff (ACTIVE); pre-ship gate before ship to peer.
- [_localsetup/tools/agentq_transport_client/](../../tools/agentq_transport_client/)  - version stamp CLI from repo root: `python3 _localsetup/tools/agentq_transport_client/agentq_cli.py stamp-prd <path>`.
