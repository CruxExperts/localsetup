from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tarfile
import zipfile

from .integrity import verify
from .artifacts import inspect_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the LocalSetup private SDK source payload without importing it.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--root", type=Path, help="Canonical source or generated private payload directory")
    source.add_argument("--artifact", type=Path, help="Public tar, sdist, or wheel; verify embedded wheel SDK SBOM")
    args = parser.parse_args(argv)
    try:
        manifest = verify(args.root) if args.root else inspect_artifact(args.artifact)["manifest"]
    except (OSError, ValueError, TypeError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"SDK payload validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "files": len(manifest["files"]),
                      "components": [{"name": c["name"], "version": c["version"]}
                                     for c in manifest["components"]]}, sort_keys=True))
    return 0
