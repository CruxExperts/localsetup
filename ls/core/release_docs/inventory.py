"""Tracked active public documentation inventory for release audits."""
from __future__ import annotations

import re
from pathlib import Path

from ls.core.git_subprocess import run_git


_PRIVATE_OR_HISTORICAL_PARTS = {
    ".agents", ".codex", ".localsetup-maint", ".ai", "archive", "archives", "audits",
    "history", "historical", "local-context", "upstream", "vendor",
}
_PUBLIC_ROOT = {"README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "REVIEW.md", "SECURITY.md", "SUPPORT.md"}
_PUBLIC_FRAMEWORK = {"ls/README.md", "ls/docs/README.md", "ls/docs/QUICKSTART.md", "ls/docs/FEATURES.md", "ls/docs/WORKFLOW_PACKAGES.md", "ls/docs/PLATFORM_REGISTRY.md"}
_GENERATED = {
    "assets/README.md", "ls/docs/SKILLS.md", "ls/docs/WORKFLOW_QUICK_REF.md", "ls/docs/WORKFLOW_REGISTRY.md",
    "ls/docs/migration/skill-alias-map.md",
}
_STATUS = re.compile(r"^status:\s*([A-Za-z-]+)\s*$", re.MULTILINE)
_OWNER = re.compile(r"^(?:owner_skill|owner_package):\s*\S+\s*$", re.MULTILINE)


def _active_framework_document(text: str) -> bool:
    if not text.startswith("---\n"):
        return False
    closing = text.find("\n---\n", 4)
    if closing < 0:
        return False
    frontmatter = text[4:closing]
    status = _STATUS.search(frontmatter)
    return bool(status and status.group(1) == "ACTIVE" and _OWNER.search(frontmatter))


def _is_active_public_document(root: Path, path: str) -> bool:
    parts = Path(path).parts
    if path == "AGENTS.md" or path.endswith("/AGENTS.md") or path.startswith("docs/"):
        return False
    if any(part in _PRIVATE_OR_HISTORICAL_PARTS for part in parts):
        return False
    if path in _GENERATED or path.startswith(("ls/docs/_generated/", "ls/docs/releases/")):
        return False
    if path in _PUBLIC_ROOT or path in _PUBLIC_FRAMEWORK:
        return True
    if path.startswith(("ls/skills/", "ls/workflows/")) and path.endswith(".md"):
        return True
    if not path.startswith("ls/docs/") or not path.endswith(".md"):
        return False
    result = run_git(root, ["show", f"HEAD:{path}"], text=True, capture_output=True, check=False)
    return result.returncode == 0 and _active_framework_document(result.stdout)


def tracked_documents(repo_root: Path) -> list[str]:
    """Return sorted tracked, active, public documentation candidates only."""
    root = Path(repo_root)
    completed = run_git(root, ["ls-files", "-z"], text=False, capture_output=True, check=True)
    paths = [part.decode("utf-8", errors="strict") for part in completed.stdout.split(b"\0") if part]
    return sorted(path for path in paths if _is_active_public_document(root, path))
