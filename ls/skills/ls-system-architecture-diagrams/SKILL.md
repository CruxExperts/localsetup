---
name: ls-system-architecture-diagrams
description: Guide system architecture diagrams. Use for C4, deployment, sequence,
  data-flow, trust-boundary, and operational diagrams.
metadata:
  version: '1.0'
---

# Architecture Diagrams

Use this skill when working on architecture diagrams tasks.

## Workflow

- Choose diagram type by question: context, container, component, deployment, sequence, data flow, or threat model.
- Keep diagrams tied to explicit assumptions, interfaces, data stores, trust boundaries, and failure modes.
- Prefer maintainable text diagrams when the repo already uses Mermaid, PlantUML, or Structurizr.

## Boundaries

- Inspect the target repository before making changes.
- Prefer existing project patterns, declared package managers, and documented validation commands.
- Do not expose secrets, credentials, private user data, or production account identifiers in source, examples, or logs.
- When external APIs or current vendor behavior matter, verify against official docs before implementation.

## Provenance

- Source classification: `localsetup-native`
- This is a Localsetup-native skill written from project workflow requirements and public/official documentation routing.
