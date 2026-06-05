"""Constants for Localsetup version planning and sync."""

from __future__ import annotations

import re

ZERO_SHA = "0" * 40
VERSION_SYNC_PREFIX = "chore: sync release version"
RELEASE_TYPE_RE = re.compile(r"^Release-Type:\s*(major|minor|patch|none)\s*$", re.MULTILINE | re.IGNORECASE)
BREAKING_CHANGE_RE = re.compile(r"^BREAKING CHANGE:", re.MULTILINE)
BREAKING_SUBJECT_RE = re.compile(r"^[a-zA-Z]+(?:\([^)]+\))?!:")
KNOWN_PATCH_TYPES = {
    "fix",
    "docs",
    "chore",
    "style",
    "refactor",
    "perf",
    "test",
    "ci",
    "build",
    "revert",
}
VERSIONED_DOC_GLOBS = ("_localsetup/docs/**/*.md",)
VERSIONED_DOC_EXCLUDED_PARTS = {"_generated", "local-context"}
INTERNAL_PATCH_PATHS = (
    ".gitignore",
    ".githooks/",
    ".github/",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "README.md",
    "install",
    "_localsetup/README.md",
    "_localsetup/config/",
    "_localsetup/docs/",
    "_localsetup/skills/",
    "_localsetup/skills/ls-automatic-versioning/",
    "_localsetup/templates/",
    "_localsetup/tests/",
    "_localsetup/core/",
)
RELEASE_TOOLING_PATHS = (
    "_localsetup/core/cli.py",
    "_localsetup/core/versioning.py",
)
