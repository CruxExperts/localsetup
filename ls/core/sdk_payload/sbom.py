"""Deterministic CycloneDX records for the retained, locally patched SDK."""
from __future__ import annotations

import hashlib
import json

SBOM_PATH = "ls/sdk-sbom.cdx.json"


def components(manifest: dict) -> list[dict]:
    result = []
    for component in sorted(manifest["components"], key=lambda c: c["name"]):
        name = component["name"]
        inventory = {p: e["sha256"] for p, e in manifest["files"].items() if e["component"] == name}
        digest = hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        properties = {"localsetup:vendored": "true", "localsetup:namespace": component["namespace"],
                      "localsetup:source-commit": component["commit"], "localsetup:inventory-sha256": digest}
        for patch in manifest["patches"]:
            if manifest["files"][patch["path"]]["component"] == name:
                properties["localsetup:patch:" + patch["path"]] = patch["sha256"]
        result.append({
            "type": "library", "name": name, "version": component["version"],
            "bom-ref": "localsetup:vendored:" + name,
            "purl": f"pkg:pypi/{name}@{component['version']}",
            "licenses": [{"license": {"id": component["license"]}}],
            "externalReferences": [{"type": "vcs", "url": component["repository"] + "/tree/" + component["commit"]},
                                   {"type": "distribution", "url": component["source_archive_url"],
                                    "hashes": [{"alg": "SHA-256", "content": component["source_archive_sha256"]}]}],
            "properties": [{"name": k, "value": v} for k, v in sorted(properties.items())],
        })
    return result


def document(manifest: dict) -> dict:
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
            "components": components(manifest)}


def encode(manifest: dict) -> bytes:
    return (json.dumps(document(manifest), indent=2, sort_keys=True) + "\n").encode()
