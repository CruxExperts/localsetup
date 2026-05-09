---
name: ls-agentic-umbrella-queue
description: "Umbrella queue guardrails for named multi-phase workflows. Use only when editing queue/PRD inputs such as .agent/queue/**, PRD.md, or *.prd.md, or when the user explicitly invokes a named umbrella workflow."
metadata:
  version: "1.1"
---

# Umbrella and queue (scope-based)

This rule applies when **queue or PRD inputs are in scope** (for example `.agent/queue/**`, `PRD.md`, or `*.prd.md`) or when the user explicitly asks to run an umbrella/workflow by name.

Do not load this skill for routine agent-state or agent-configuration edits that are not queue files, PRDs, queue manifests, or a clear named umbrella workflow invocation.

## Named workflows

- Workflows have **distinct names**. Execute only on **clear user intent** (e.g. "Please execute the umbrella workflow X", "Run make-it-happen").
- Do not start an umbrella or queue run without the user having asked for it by name or by editing queue/PRD inputs with clear intent.
- Treat broad references to `.agent/` as insufficient by themselves; confirm that the requested work is queue, PRD, or named-workflow work before activating the umbrella protocol.

## Umbrella invariants

- **Single kickoff:** The user invokes one named workflow; after required confirmation, run the defined phases without asking for repeated "continue" approvals.
- **No mid-run stop:** Continue to completion or to a defined workflow gate; do not pause between ordinary sub-steps unless the workflow spec defines that gate.
- **PHC gates:** For destructive or high-impact steps, present the impact and wait for explicit pre-human confirmation before proceeding.
- **Single final webhook:** Send one final outcome or notification at the end, rather than multiple intermediate pings.

## Guardrails

- **Impact summary + user confirmation:** Before running **big, complex, or destructive** workflows, present a short impact summary (what will change, what could be affected) and require explicit user confirmation. Do not proceed without user acknowledgment.
- **Scope:** This rule does not activate for routine edits outside queue/PRD inputs, unrelated agent files, or general agent configuration work; it activates when queue/PRD inputs are in scope or when a named workflow is invoked.

## References

- [_localsetup/docs/WORKFLOW_REGISTRY.md](../../docs/WORKFLOW_REGISTRY.md)  - list of named workflows, when to use, impact review required.
- [_localsetup/docs/AGENTIC_UMBRELLA_WORKFLOWS.md](../../docs/AGENTIC_UMBRELLA_WORKFLOWS.md)  - umbrella definition, no mid-run stop, PHC gates, single final webhook.
- [_localsetup/docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](../../docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md)  - spec format, external confirmation protocol.
