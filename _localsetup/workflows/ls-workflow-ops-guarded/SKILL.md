---
name: ls-workflow-ops-guarded
description: Use when risky operations need approval checkpoints, impact review, or guarded execution; hand off sudo, elevated, PTY, or interactive password execution to ls-workflow-ops-tmux-session.
metadata:
  version: "1.0"
---

Use this workflow package for HITL and destructive-operation safeguards, approval checkpoints, and impact review before risky commands. When the blocker is `sudo`, root/admin elevation, `require_escalated`, pseudo-terminal/PTY handling, or an interactive password prompt, use `ls-workflow-ops-tmux-session` for the execution handoff.

Primary reference: `_localsetup/docs/WORKFLOW_REGISTRY.md`.
