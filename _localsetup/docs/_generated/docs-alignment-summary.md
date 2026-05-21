---
status: ACTIVE
version: 4.0
owner_package: docs-align
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 6c8102a2ccfcd9147839d9d72b4243f8738735f8bfe9156692cf19f6f63c95f7
  emitter: docs-align
framework_version: 4.0.5
source_commit: 60e9ad92385a591a93c347da6ef655c1e701b84c
artifact_sha256: 56d6369b97a701b47b41d77dcca909cf8533a801c8b8694394cf8cce8616b4c2
---
# Documentation Alignment Summary

This page is generated from repository inventory, source-truth manifests, asset metadata, and the docs-alignment audit.

| Signal | Value |
|---|---:|
| Version | `4.0.5` |
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
