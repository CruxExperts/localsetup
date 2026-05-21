---
status: ACTIVE
version: 4.0
owner_package: docs-align
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 51b63a114c70cc5c4eaf62dce4bed354e71a444efef6cfe273b9710c8a75a4a3
  emitter: docs-align
framework_version: 4.0.4
source_commit: f94c1205fb06a5700e0f6f360e9795c70443d43a
artifact_sha256: 76d72ffbcee776e962ccdef1d9d1e29e93e7c0d614e1993953c66d8bf2133d90
---
# Documentation Alignment Summary

This page is generated from repository inventory, source-truth manifests, asset metadata, and the docs-alignment audit.

| Signal | Value |
|---|---:|
| Version | `4.0.4` |
| Public/framework docs scanned | 339 |
| Shipped skills | 53 |
| Workflow packages | 22 |
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
- `major` `stale_count` _localsetup/docs/FEATURES.md:37: hard-coded shipped skill/workflow count is stale
