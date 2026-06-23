---
name: ls-workflow-planning-critic-loop
description: Use when creating decision-complete plans through grounding, capped clarification, subagent delegation, and critic iteration.
metadata:
  version: "1.0"
---

Use this workflow package for non-trivial planning work where the agent must produce a structured plan before implementation, handoff, or approval.

Ground first: inspect available repo files, docs, config, schemas, current GitHub state, or local system facts before asking the user. Do not ask questions that non-mutating inspection can answer.

Clarify only when it materially changes the plan. Ask at most three user questions total, one at a time, using the reverse decision-tree style from `_localsetup/docs/DECISION_TREE_WORKFLOW.md`: A-D options, preferred choice, and rationale. Use available question/input/TUI tooling when supported; otherwise render clear markdown or plain-text choices. This three-question cap is local to this planning workflow and does not change the default `ls-workflow-spec-clarify-reverse` protocol.

For non-trivial plans, use subagents when they reduce risk or context load: `explorer` for broad repo discovery, `researcher` for current external facts, `tester` for validation plans or long command logs, and `reviewer` as the critic. Keep the controller responsible for verification, checkpoints, and final plan quality. Do not force delegation for trivial direct tasks.

Run critic iterations before emitting the final `<proposed_plan>` for non-trivial work. Complete at least three reviewer/critic passes unless the task is clearly trivial/direct. Continue until the critic reports at least 90 percent satisfaction and no high-severity findings. Score satisfaction from concrete review dimensions: requirement coverage, unresolved decisions, grounding evidence, delegation fit, validation plan, risk handling, and scope control. Deduct for each unresolved issue by severity instead of asserting a percentage. Stop after five failed iterations and surface the blockers instead of forcing a weak plan.

Primary references: `_localsetup/docs/DECISION_TREE_WORKFLOW.md`, `_localsetup/docs/WORKFLOW_STANDARD.md`, `_localsetup/docs/WORKFLOW_PACKAGES.md`, and `_localsetup/docs/SKILLS_AND_RULES.md`.
