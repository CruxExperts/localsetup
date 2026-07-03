---
status: ACTIVE
version: 4.2
owner_package: docs-align
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 2978a9b72fcb7e0273abd61a722e320abebac825766e7aba9aebd45449ade982
  emitter: docs-align
framework_version: 4.2.7
source_commit: fbe06c27b01f16a1fa7a164329a7448db199850d
artifact_sha256: d1c49d2ad9fadee58c3dfc945630f7c6f20a92f3912b54c9061673b14a4f187d
---
# Documentation Alignment Summary

This page is generated from repository inventory, source-truth manifests, asset metadata, and the docs-alignment audit.

| Signal | Value |
|---|---:|
| Version | `4.2.7` |
| Public/framework docs scanned | 425 |
| Shipped skills | 105 |
| Workflow packages | 23 |
| Supported platforms | 6 |
| Audit findings | 2 |
| Critical findings | 0 |
| Major findings | 2 |

## Generated Artifacts

- `docs-inventory.json`: scanned docs, skills, workflows, assets, CI workflows, and CLI commands.
- `docs-truth-map.json`: claims and their backing source files.
- `docs-audit-result.json`: JSON-first findings for drift and Markdown/doc hygiene.
- `docs-asset-manifest.json`: asset metadata and references.

## Findings

- `major` `stale_count` README.md:28: hard-coded shipped skill/workflow count is stale
- `major` `stale_count` _localsetup/docs/FEATURES.md:38: hard-coded shipped skill/workflow count is stale
