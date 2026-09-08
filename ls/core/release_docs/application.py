"""Apply accepted proposals with exact-source and path checks."""
from __future__ import annotations

import json
from pathlib import Path

from .github import git


def apply_candidate(root: Path, plan: dict, candidate: dict) -> dict:
    from .content import validate_record
    from .proposals import validate_proposal
    from .render import render_outputs
    from .safety import check_public_text

    if git(root, "status", "--porcelain"):
        raise ValueError("Preparation requires a clean checkout; preserve unrelated work first")
    validated = validate_proposal(root, plan, candidate)
    record = validate_record(validated["record"])
    check_public_text(json.dumps(record))
    for item in validated["edits"]:
        check_public_text(item["content"])
    if git(root, "rev-parse", "HEAD") != plan["source_commit"]:
        raise ValueError("Documentation candidate is stale")
    updates = {item["path"]: item["content"] for item in validated["edits"]}
    original: dict[str, bytes | None] = {}
    try:
        # Render after editorial edits so surrounding authored text survives.
        for relative, text in updates.items():
            path = root / relative
            original[relative] = path.read_bytes()
            path.write_text(text, encoding="utf-8")
        generated = render_outputs(root, record)
        generated[f"ls/docs/releases/{record['version']}.json"] = json.dumps(record, indent=2) + "\n"
        for relative, text in generated.items():
            path = root / relative
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Release output path escapes the checkout")
            original.setdefault(relative, path.read_bytes() if path.exists() else None)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        from .checks import check
        result = check(root, record, target_version=plan["target_version"])
        # Version synchronization follows the authored candidate commit. All
        # non-version findings must already be resolved before integration.
        if not result["ok"]:
            raise ValueError("Rendered documentation candidate failed checks: " + json.dumps(result["findings"]))
    except BaseException:
        for relative, data in original.items():
            path = root / relative
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)
        raise
    changed = sorted(relative for relative, before in original.items()
                     if before != (root / relative).read_bytes())
    return {"ok": True, "source_commit": plan["source_commit"], "changed_paths": changed}
