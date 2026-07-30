from __future__ import annotations

from pathlib import Path

SCHEMA_VERSION = "1.0"
GENERATED_DIR = Path("ls/docs/_generated")
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
    ".agents/state",
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
    "ls/README.md",
    "ls/docs/README.md",
    "ls/docs/QUICKSTART.md",
    "ls/docs/FEATURES.md",
    "ls/docs/WORKFLOW_PACKAGES.md",
    "ls/docs/PLATFORM_REGISTRY.md",
)
