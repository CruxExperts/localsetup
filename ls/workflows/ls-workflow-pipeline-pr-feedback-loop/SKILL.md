---
name: ls-workflow-pipeline-pr-feedback-loop
description: Use when turning pull request feedback into fixes, tests, and follow-up review.
metadata:
  version: "1.0"
---

Use this pipeline package for structured PR feedback loops.
Follow the owning skills in sequence:

1. [ls-receiving-code-review](../../skills/ls-receiving-code-review/SKILL.md)
   for technical triage and verification of actionable feedback.
2. [ls-tdd-guide](../../skills/ls-tdd-guide/SKILL.md) for implementing accepted
   fixes with test evidence.
3. [ls-pr-reviewer](../../skills/ls-pr-reviewer/SKILL.md) for follow-up automated
   review.

These skills own the procedures; this package composes their phases.
