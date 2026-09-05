---
name: ls-workflow-pipeline-pre-publish
description: Use when running pre-publish checks, version sync, and framework audit before release actions.
metadata:
  version: "1.0"
---

Use this pipeline package to prepare a repo for publishing.
Follow [ls-github-publishing-workflow](../../skills/ls-github-publishing-workflow/SKILL.md)
for publishing readiness, `ls-automatic-versioning` and
[VERSIONING.md](../../docs/VERSIONING.md) for version consistency, then
[ls-framework-audit](../../skills/ls-framework-audit/SKILL.md) for audit checks.
These owners define the procedures. This pipeline prepares readiness evidence;
release actions remain with the publishing skill and its authorization gates.
