---
name: ls-workflow-pipeline-repo-convert
description: Use when converting an existing repo to the current Localsetup framework with backup, blocker, install, and verification gates.
metadata:
  version: "1.0"
---

Use this workflow when onboarding a repository that may already contain old Localsetup files, adapter paths, lockfiles, or framework source.

Primary command:

```bash
localsetup convert --tools codex --packs core --yes
```

Run a dry report first when unmanaged project content may exist:

```bash
localsetup convert --tools codex --packs core
```

Follow `_localsetup/docs/REPO_CONVERSION.md` for source-vs-target behavior, backup expectations, blockers, and final verification.
