---
status: ACTIVE
version: 4.25
owner_package: docs-align
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 3d7439ab2104acc29ae960b7888a4cca46f6b8a39e2596d32a15c203a2d17c2b
  emitter: docs-align
framework_version: 4.25.0
source_commit: b31f22a1fa78aafb63dc462182b4f973cec7bff1
artifact_sha256: 0ca8094ed3969db9cdf61c5055c67ec8a7cc9e614d3363b59fe986b6657905be
---
# Documentation Alignment Summary

This page is generated from repository inventory, source-truth manifests, asset metadata, and the docs-alignment audit.

| Signal | Value |
|---|---:|
| Version | `4.25.0` |
| Documentation files inventoried | 506 |
| Immutable upstream documents | 64 |
| Shipped skills | 105 |
| Workflow packages | 16 |
| Supported platforms | 20 |
| Audit findings | 2 |
| Critical findings | 0 |
| Major findings | 2 |

## Generated Artifacts

- `docs-inventory.json`: scanned docs, skills, workflows, assets, CI workflows, and CLI commands.
- `docs-truth-map.json`: claims and their backing source files.
- `docs-audit-result.json`: JSON-first findings for drift and Markdown/doc hygiene.
- `docs-asset-manifest.json`: asset metadata and references.

## Findings

- `major` `stale_count` README.md:44: hard-coded shipped skill/workflow count is stale
- `major` `stale_count` ls/docs/FEATURES.md:54: hard-coded shipped skill/workflow count is stale
