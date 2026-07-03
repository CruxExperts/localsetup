---
status: ACTIVE
version: 4.2
owner_package: docs-align
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: a00e1492fe5c18444c3d358f734d978bac740735f5b176a9b78c7f29659c1e18
  emitter: docs-align
framework_version: 4.2.6
source_commit: d9b5652b6d1e36aa1865e4055a0ba97d22d5a286
artifact_sha256: 7fb8c7cdeabd161c911afa57029216984eb36febe0a2aa9955183dc5ad7b6c10
---
# Documentation Alignment Summary

This page is generated from repository inventory, source-truth manifests, asset metadata, and the docs-alignment audit.

| Signal | Value |
|---|---:|
| Version | `4.2.6` |
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
