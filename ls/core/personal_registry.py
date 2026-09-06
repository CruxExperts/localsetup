"""Retain personal installation references independently of repository receipts."""
import hashlib
import json
from .installation_ownership import InstallationOwner


def record_personal_owners(registry: dict, adapters: list[dict], available: set[str]) -> None:
    """Update explicit personal owners; caller holds the shared package-root lock."""
    selected: dict[str, dict] = {}
    for adapter in adapters:
        for raw in adapter.get("owners", []):
            owner = InstallationOwner(**raw)
            if owner.scope != "personal":
                continue
            encoded = json.dumps(owner.wire(), sort_keys=True, separators=(",", ":"))
            key = "personal:" + hashlib.sha256(encoded.encode()).hexdigest()
            record = selected.setdefault(key, {"owner": owner.wire(), "packages": set(), "paths": set()})
            names = set(adapter.get("packages", []))
            if not names <= available:
                raise ValueError("Personal owner references unavailable packages")
            record["packages"].update(names)
            record["paths"].add(str(adapter["path"]))
    if not selected:
        return
    owners = registry.setdefault("personal_owners", {})
    for key, record in selected.items():
        names = record["packages"]
        for name, package in registry["packages"].items():
            refs = set(package.get("refs", []))
            refs.discard(key)
            if name in names:
                refs.add(key)
            package["refs"] = sorted(refs)
        owners[key] = {"owner": record["owner"], "packages": sorted(names), "paths": sorted(record["paths"])}
