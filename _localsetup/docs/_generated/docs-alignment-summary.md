---
status: ACTIVE
version: 4.2
owner_package: docs-align
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 1ce59af85c850b2c775fc39d27b200229d9d809b51934a3373445f1718bc30dc
  emitter: docs-align
framework_version: 4.2.9
source_commit: befb112f2d7c8ffe215dead3525e324719bbfc9d
artifact_sha256: fded9775885b85dfaf97c00eadeb056c43ad9d7f0f706f9afaad0000fd83ee0d
---
# Documentation Alignment Summary

This page is generated from repository inventory, source-truth manifests, asset metadata, and the docs-alignment audit.

| Signal | Value |
|---|---:|
| Version | `4.2.9` |
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
