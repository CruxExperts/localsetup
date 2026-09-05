"""Expose immutable upstream document ownership to documentation inventories."""
from __future__ import annotations

from pathlib import Path

from .integrity import verify


def upstream_documents(repo_root: Path) -> dict[str, dict[str, str]]:
    root = repo_root / "vendor" / "lscli"
    if not root.exists() and not root.is_symlink():
        return {}
    manifest = verify(root)
    components = {c["name"]: c for c in manifest["components"]}
    documents = {}
    for path, entry in manifest["files"].items():
        if (not path.endswith(".md") or entry["role"] != "runtime"
                or entry["sha256"] != entry["upstream_sha256"]):
            continue
        component = components[entry["component"]]
        documents["vendor/lscli/" + path] = {
            "owner": component["name"],
            "source_url": (component["repository"] + "/blob/" + component["commit"]
                           + "/" + component["source_prefix"] + path),
            "upstream_sha256": entry["upstream_sha256"],
        }
    return documents
