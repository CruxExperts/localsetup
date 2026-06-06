---
status: ACTIVE
version: 4.1
owner_skill: ls-agentq-transport
---

# Agent Q (queue) pattern (Localsetup)

**Purpose:** Pattern for processing a queue of PRD/spec items: locate specs, implement per spec, update status, write outcome. Used when the user says "process PRDs" or "run batch from PRD folder".

## Queue flow

1. **Locate** - Find PRD/spec files in the configured path (e.g. `.agent/queue/`). Filter by status (e.g. `ready`, `in-progress`). Sort by priority and date.
2. **Implement** - For each spec, follow Implementation steps and Acceptance criteria; use [PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md) for format and outcome template.
3. **Status** - Set `status: in-progress` when starting; `status: done` or `blocked` when finished.
4. **Outcome** - Append outcome block (branch, commit SHA, files changed, verification, rollback) per spec.
5. **Clean-tree** - Before marking done, ensure repo is clean (commit or revert as needed).
6. **External confirmation** - If spec has `external_confirmation: acknowledged` or equivalent, agent may skip human impact confirmation; otherwise follow guardrails.

## Queue layout (structured optional)

When using agent-to-agent transports, a **structured** layout may exist under the queue root. **This document only defines the filesystem layout and batch behavior; OpenPGP envelopes, registry rules, `to_agent_ids`, ack routing, and delivery/deliverable semantics are defined in [AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](AGENTIC_AGENT_TO_AGENT_PROTOCOL.md) and [AGENTIC_AGENT_Q_SCENARIOS.md](AGENTIC_AGENT_Q_SCENARIOS.md).**

| Folder | Role |
|--------|------|
| **inbox** | Incoming from transport adapters (staging then promote). |
| **in** | Ready to process (`status: ready` or resume `in-progress`). |
| **out** | Sent sidecars (message_id, transport_ref). |
| **pending** | Awaiting ack or handoff. |
| **archive** | B retains shipped context per `conversation_id`; do not commit. |

**Flat (backwards compatible):** If only `.agent/queue/` exists with no subdirs, treat the whole folder as **in** (current behavior). Human may still drop PRDs directly into `in/` or flat queue without going through transport.

**Agent-to-agent:** See [AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](AGENTIC_AGENT_TO_AGENT_PROTOCOL.md) (ACTIVE), [AGENTIC_AGENT_Q_SCENARIOS.md](AGENTIC_AGENT_Q_SCENARIOS.md) for repo/agent/local/remote setups, and [AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md](AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md) for transport-agnostic handoff, OpenPGP, registry, pre-ship gate, and iteration.

## Reference

- [PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md) - Spec format, front matter, outcome template.
- [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) - When to use Agent Q and impact review.
