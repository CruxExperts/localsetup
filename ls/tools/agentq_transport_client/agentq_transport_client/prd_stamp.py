#!/usr/bin/env python3
# Purpose: Stamp PRD front matter with localsetup_framework_version (and optional hash).
# Created: 2026-03-09
# Last updated: 2026-03-09

"""Ensure PRD markdown has framework version fields when tooling writes it."""

from __future__ import annotations

import sys
from pathlib import Path

# lib on path when run via agentq_cli
_ENGINE = Path(__file__).resolve().parents[3]
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))
from lib.deps import require_deps  # noqa: E402

require_deps(["frontmatter", "yaml"])

import frontmatter  # noqa: E402

from agentq_transport_client.version_util import (  # noqa: E402
    read_framework_hash,
    read_framework_version,
)


def ensure_prd_stamp(path: Path, *, add_hash: bool = False) -> bool:
    """Load PRD at path, set localsetup_framework_version if absent, write back.
    Returns True if file was modified."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    post = frontmatter.load(path)
    meta = dict(post.metadata) if post.metadata else {}
    changed = False
    if not meta.get("localsetup_framework_version"):
        meta["localsetup_framework_version"] = read_framework_version()
        changed = True
    if add_hash and not meta.get("localsetup_framework_hash"):
        h = read_framework_hash()
        if h:
            meta["localsetup_framework_hash"] = h
            changed = True
    if not changed:
        return False
    post.metadata = meta
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return True
