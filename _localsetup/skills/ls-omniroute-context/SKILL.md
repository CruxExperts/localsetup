---
name: ls-omniroute-context
description: OmniRoute context, compression, memory, cache, RTK, and Qdrant configuration workflows. Use for context engineering, prompt compression, memory settings, cache diagnostics, and related safety checks.
metadata:
  version: "1.0"
extensions:
  omniroute:
    source_kind: localsetup-native
    local_role: context-compression
    source_repo: https://github.com/diegosouzapw/OmniRoute
    source_ref: main
    source_commit: 0c7f756f922fe3c0408e41852577027b496489bf
    package_version: 3.8.43
    release_package_commit: b729a8f27364f072c87082e03bb8e122f3d76251
---

# OmniRoute Context And Compression

Purpose: manage OmniRoute context engineering, compression discovery, memory, cache, RTK filters, and related settings with Localsetup safety boundaries.

## Start With Preflight

```bash
python3 "$(python3 _localsetup/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" preflight \
  --required-access read
```

Use `--required-access admin` before changing compression settings, memory settings, cache behavior, or Qdrant connection details.

## Scope

Use this skill for:

- `/api/compression/*` and `/api/settings/compression*`
- `/api/context/*`
- `/api/cache/*`
- `/api/memory/*` and `/api/settings/memory`
- `/api/settings/qdrant*`
- RTK filters, context relay, prompt compression tests, and cache diagnostics.

Do not write Qdrant credentials, memory backends, system prompts, payload rules, or shell startup files without explicit user approval. Do not print or commit Qdrant credentials, provider tokens, API keys, or payloads that may contain secrets.

## Commands

```bash
python3 "$(python3 _localsetup/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" request GET /api/settings/compression
python3 "$(python3 _localsetup/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" request GET /api/cache/stats
python3 "$(python3 _localsetup/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" request GET /api/settings/qdrant
```

Use `ls-omniroute-admin-automation` for planned writes because it provides snapshots, audit logs, dry-run reconciliation, and explicit safety flags.

## Upstream Coverage

Covers upstream v3.8.43 skills:

- `omni-compression`
- `omni-context-rtk`
- `omni-cache`
- `cli-compression`
- `cli-contexts`
