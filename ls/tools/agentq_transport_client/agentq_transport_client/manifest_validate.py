#!/usr/bin/env python3
# Purpose: Validate inner manifest bounds (manifest.schema.json rules without jsonschema dep).
# Created: 2026-03-09
# Last updated: 2026-03-09

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agentq_transport_client.crypto_pipeline import CryptoPipelineError

_SHA256 = re.compile(r"^[a-f0-9]{64}$")


_SCHEMA_PATH = None  # lazy


def _schema_path() -> Path | None:
    global _SCHEMA_PATH
    if _SCHEMA_PATH is not None:
        return _SCHEMA_PATH if _SCHEMA_PATH.exists() else None
    # agentq_transport_client -> tools/agentq_transport_client -> ls
    base = Path(__file__).resolve().parents[3]
    p = base / "config" / "manifest.schema.json"
    _SCHEMA_PATH = p
    return p if p.is_file() else None


def validate_manifest(manifest: dict[str, Any]) -> None:
    """
    Enforce manifest.schema.json bounds. Raises CryptoPipelineError MANIFEST_INVALID.
    """
    if not isinstance(manifest, dict):
        raise CryptoPipelineError("MANIFEST_INVALID", "Manifest must be an object.")
    if not manifest.get("manifest_version"):
        raise CryptoPipelineError("MANIFEST_INVALID", "manifest_version required.")
    from_id = manifest.get("from_agent_id")
    if not from_id or not isinstance(from_id, str):
        raise CryptoPipelineError("MANIFEST_INVALID", "from_agent_id required string.")
    if len(from_id) > 256:
        raise CryptoPipelineError("MANIFEST_INVALID", "from_agent_id too long.")
    ids = manifest.get("to_agent_ids")
    if ids is not None:
        if not isinstance(ids, list) or len(ids) > 16:
            raise CryptoPipelineError("MANIFEST_INVALID", "to_agent_ids must be list max 16.")
        for i, x in enumerate(ids):
            if not isinstance(x, str) or not x.strip():
                raise CryptoPipelineError("MANIFEST_INVALID", f"to_agent_ids[{i}] invalid.")

    att = manifest.get("attachments")
    if att is not None:
        if not isinstance(att, list):
            raise CryptoPipelineError("MANIFEST_INVALID", "attachments must be array.")
        if len(att) > 32:
            raise CryptoPipelineError("MANIFEST_INVALID", "attachments max 32.")
        for i, row in enumerate(att):
            if not isinstance(row, dict):
                raise CryptoPipelineError("MANIFEST_INVALID", f"attachments[{i}] not object.")
            path = row.get("path")
            sha = row.get("sha256")
            if not path or not isinstance(path, str):
                raise CryptoPipelineError("MANIFEST_INVALID", f"attachments[{i}].path required.")
            if len(path) > 512:
                raise CryptoPipelineError("MANIFEST_INVALID", f"attachments[{i}].path too long.")
            if not sha or not isinstance(sha, str) or not _SHA256.match(sha.lower()):
                raise CryptoPipelineError(
                    "MANIFEST_INVALID", f"attachments[{i}].sha256 must be 64 hex chars."
                )
            if "bytes" in row and row["bytes"] is not None:
                b = row["bytes"]
                if not isinstance(b, int) or b < 0 or b > 1073741824:
                    raise CryptoPipelineError("MANIFEST_INVALID", f"attachments[{i}].bytes out of range.")

    it = manifest.get("iteration")
    if it is not None and (not isinstance(it, int) or it < 1):
        raise CryptoPipelineError("MANIFEST_INVALID", "iteration must be integer >= 1.")

    sp = _schema_path()
    if sp:
        try:
            import json

            import jsonschema  # type: ignore

            schema = json.loads(sp.read_text(encoding="utf-8"))
            jsonschema.validate(instance=manifest, schema=schema)
        except ImportError:
            pass
        except Exception as exc:
            raise CryptoPipelineError("MANIFEST_INVALID", f"jsonschema: {exc}") from exc
