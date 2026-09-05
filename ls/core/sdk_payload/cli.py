from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .integrity import verify


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the LocalSetup private SDK source payload without importing it.")
    parser.add_argument("--root", type=Path, required=True, help="Canonical vendor/lscli or generated private payload directory")
    args = parser.parse_args(argv)
    try:
        manifest = verify(args.root)
    except (OSError, ValueError, TypeError) as exc:
        print(f"SDK payload validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "files": len(manifest["files"]),
                      "components": [{"name": c["name"], "version": c["version"]}
                                     for c in manifest["components"]]}, sort_keys=True))
    return 0
