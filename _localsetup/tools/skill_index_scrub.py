#!/usr/bin/env python3
# Purpose: Audit PUBLIC_SKILL_INDEX.yaml for dead URLs, stub descriptions, and schema gaps.
#          Thin compatibility wrapper for _localsetup.core.skill_index_scrub.

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCALSETUP_LIB = REPO_ROOT / "_localsetup" / "lib"

for path in (REPO_ROOT, LOCALSETUP_LIB):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from deps import require_deps  # noqa: E402

require_deps(["yaml", "requests", "frontmatter"])

from _localsetup.core.skill_index_scrub.cli import main  # noqa: E402
from _localsetup.core.skill_index_scrub.index_io import apply_fixes  # noqa: E402,F401


if __name__ == "__main__":
    sys.exit(main())
