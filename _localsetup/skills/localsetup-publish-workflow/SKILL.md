---
name: localsetup-publish-workflow
description: Run the framework publish workflow from repo root. Bumps version from last commit (Conventional Commits), regenerates doc artifacts, commits the sync, and optionally pushes. Use when the user says "publish", "run publish workflow", "bump and push", "sync version and docs", or "run maintain/publish".
metadata:
  version: "1.0"
---

# Publish workflow (Localsetup v2)

**Purpose:** When the user asks to run the publish workflow (or equivalent), run it from repo root so version and generated docs stay in sync and are committed (and optionally pushed).

## When to load this skill

- User says "publish", "run publish", "run the publish workflow", "bump and push", "sync version and docs", "run maintain", or similar.
- User wants to commit a version bump and doc sync after making framework changes.
- Task is to "do the publish workflow" or "run what runs after I commit".

## What to do

1. **From repo root**, run:
   ```bash
   ./scripts/publish --push
   ```
   This: bumps VERSION from the last commit message (feat: → minor, fix:/docs: → patch), regenerates SKILLS.md and facts blocks, commits with `chore: bump to X.Y.Z and sync docs`, and pushes to origin main.

2. **If the user only wants to commit locally** (no push), run:
   ```bash
   ./scripts/publish
   ```
   Then they can run `git push origin main` when ready.

3. **If the user wants a specific bump type**, run:
   ```bash
   ./scripts/publish --major   # or --minor or --patch
   ./scripts/publish --minor --push
   ```

4. **Report the result:** Show the script output (new version, "Published: X.Y.Z", or any error). If the script says "Nothing to commit", the working tree was already in sync.

## Prerequisites

- Run from the **repository root** (where VERSION and scripts/ live).
- User should have already committed their changes; publish adds a separate commit for the version bump and doc sync.
- For `--push`, the remote must be configured and the user must have push access.

## See also

- docs/VERSIONING.md – how bump type is inferred, manual bump options.
- docs/MAINTENANCE_WORKFLOW.md – when to run publish, policy.
