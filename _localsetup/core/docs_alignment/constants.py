from __future__ import annotations

from pathlib import Path

SCHEMA_VERSION = "1.0"
GENERATED_DIR = Path("_localsetup/docs/_generated")
SUMMARY_PATH = GENERATED_DIR / "docs-alignment-summary.md"
INVENTORY_PATH = GENERATED_DIR / "docs-inventory.json"
TRUTH_MAP_PATH = GENERATED_DIR / "docs-truth-map.json"
AUDIT_PATH = GENERATED_DIR / "docs-audit-result.json"
ASSET_MANIFEST_PATH = GENERATED_DIR / "docs-asset-manifest.json"
ASSETS_README = Path("assets/README.md")
LIFECYCLE_STATES = {"ACTIVE", "PROPOSAL", "DRAFT", "DEPRECATED", "ARCHIVED"}
LOCAL_DOC_EXCLUDES = {
    ".git",
    ".cache",
    ".codex",
    ".claude",
    ".cursor",
    ".kilo",
    ".localsetup",
    ".localsetup-maint",
    ".opencode",
    ".openclaw",
    ".pytest_cache",
    ".venv",
    ".venv-codex",
    "__pycache__",
    "localsetup.egg-info",
    "node_modules",
    "state",
}
PUBLIC_DOCS = (
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "SUPPORT.md",
    "_localsetup/README.md",
    "_localsetup/docs/README.md",
    "_localsetup/docs/QUICKSTART.md",
    "_localsetup/docs/FEATURES.md",
    "_localsetup/docs/WORKFLOW_PACKAGES.md",
    "_localsetup/docs/PLATFORM_REGISTRY.md",
)
