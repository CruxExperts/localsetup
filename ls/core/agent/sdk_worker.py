"""Provider-free isolated SDK worker qualification; dispatch remains gated."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

from .sdk_imports import activate
from ..sdk_payload.integrity import COMPONENTS


def main() -> int:
    try:
        if sys.argv[1:] != ['--probe'] or not sys.flags.isolated or not sys.dont_write_bytecode:
            raise ValueError('SDK worker requires isolated Python, disabled bytecode writes and --probe')
        package = Path(__file__).resolve().parents[2]
        if not package.is_relative_to(Path(sys.prefix).resolve()):
            raise ValueError('SDK worker must run from its installed environment')
        finder = activate(package / '_sdk_payload')
        for name in COMPONENTS.values():
            importlib.import_module(name)
        origins = finder.verify_origins()
        print(json.dumps({'schema_version': 1, 'status': 'qualified', 'origins': origins}, sort_keys=True))
        return 0
    except (ImportError, OSError, ValueError, TypeError, RuntimeError, RecursionError) as exc:
        print(f'SDK worker qualification failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
