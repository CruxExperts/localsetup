# Docs Routing Reference

This reference contains the schemas, examples, and validation scenarios for `ls-docs-organization`. Keep the root `SKILL.md` compact and use this file for detailed implementation guidance.

## Input Payload

Required fields:

- `intent`: short natural-language description of what the doc is for.
- `title`: proposed human title.

Optional fields:

- `summary`: one to three sentence description of the expected content.
- `doc_type_hint`: coarse type such as `runbook`, `adr`, `spec`, `how_to`, `notes`, or `reference`.
- `tags`: list of component, domain, feature, or workflow tags.
- `allow_nonstandard_docs`: boolean override flag, default false.

Example:

```yaml
intent: "Document how to rotate API keys for the payments service"
title: "Payments API key rotation runbook"
summary: "Step by step runbook for rotating API keys in production for the payments service."
doc_type_hint: "runbook"
tags:
  - "payments"
  - "api-keys"
  - "runbook"
allow_nonstandard_docs: false
```

## Output Payload

Return the recommendation and any warnings in a structured shape:

```yaml
category_label: "runbook"
category_slug: "incident-runbooks"
component_slug: "payments"
proposed_path: "docs/incident-runbooks/payments"
filename: "payments-api-key-rotation.md"
index_entry:
  id: "docs-incident-runbooks-payments-api-key-rotation"
  path: "docs/incident-runbooks/payments/payments-api-key-rotation.md"
  title: "Payments API key rotation runbook"
  category_label: "runbook"
  category_slug: "incident-runbooks"
  component_slug: "payments"
  status: "ACTIVE"
  last_updated: "2026-05-09"
  doc_type: "runbook"
  tags:
    - "payments"
    - "api-keys"
    - "runbook"
  nonstandard_location: false
warnings: []
```

Warnings should include `nonstandard_location` when the selected path differs from the recommended placement.

## Category Manifest

Optional repo-local manifest:

- Path: `docs/.docs-classifications.yaml`
- Purpose: record known documentation categories and their folder slugs.

Each entry should include:

```yaml
- label: "runbook"
  slug: "incident-runbooks"
  description: "Operational procedures and recovery playbooks."
```

Classification behavior:

- Load the manifest when present.
- Reuse a fitting label and slug before creating a new category.
- Append a new label and slug only when no existing category fits.
- Treat the manifest as repo-local configuration, not framework-owned state.

## Optional Config

Optional repo-local config:

- Path: `docs.config.yaml`
- Purpose: override defaults for a specific repository.

Supported fields:

```yaml
root: "docs"
categories:
  runbook:
    slug: "incident-runbooks"
    description: "Operational procedures and recovery playbooks."
aliases:
  playbook: "runbook"
required_front_matter_fields:
  - "status"
  - "last_updated"
  - "doc_type"
  - "tags"
```

When config exists, use it before heuristics and before the category manifest.

## Slug Examples

- `Incident runbooks` becomes `incident-runbooks`.
- `API reference` becomes `api-reference`.
- `User settings panel` becomes `user-settings-panel`.

Use lowercase ASCII, replace separators with hyphens, and remove characters unsafe for common filesystems.

## Reuse Examples

Strong update candidates:

- Same `component_slug` and very similar title.
- Same `category_label` and overlapping tags where the topic is clearly the same.
- Existing `docs/index.yaml` entry whose path and title match the requested work.

Weak candidates:

- Same broad category but different component.
- Same tag with an unrelated title.
- Similar filename but unrelated metadata.

When a strong candidate exists, recommend updating the existing path and include the proposed new path only as context.

## Document Metadata

Managed docs should include front matter or a compact metadata header with at least:

```yaml
status: "ACTIVE"
last_updated: "2026-05-09"
doc_type: "runbook"
tags:
  - "payments"
  - "api-keys"
```

Use lifecycle values from the repo's documentation lifecycle guidance when present. Refresh `last_updated` on significant changes.

## Human Index Shape

`docs/INDEX.md` should be derived from `docs/index.yaml`. A typical category section is:

```markdown
## Runbooks

- Payments API key rotation runbook (`incident-runbooks/payments/payments-api-key-rotation.md`) - payments, api-keys
```

Choose one ordering rule within each category, usually alphabetical by title or descending by `last_updated`, and keep it consistent.

## Validation Scenarios

New repo:

- Start with no `docs/` directory.
- Create one architecture doc, one runbook, and one how-to.
- Verify docs folders, `docs/index.yaml`, and `docs/INDEX.md` are created and aligned.

Messy existing repo:

- Start with ad hoc docs and partial topic coverage.
- Add a doc request for an already-covered topic.
- Verify the skill recommends updating the existing doc when appropriate.

Move and rename:

- Move a managed doc from one folder to another.
- Verify the path changes, the stable `id` stays the same, and both indexes update.

Override:

- Intentionally write a doc outside the recommended location with `allow_nonstandard_docs: true`.
- Verify the warning is present and the index entry sets `nonstandard_location: true`.
