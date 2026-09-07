"""Bounded read-only profile choices; never resolve credentials or providers."""
from __future__ import annotations

import json
from pathlib import Path
import threading
import time

from .profiles import document, parse
from .run_io import Streams, safe


def inventory(path: Path) -> dict:
    return validate(document(path))


def validate(profiles: dict) -> dict:
    """Validate an already parsed document without reading it a second time."""
    if len(profiles) > 256:
        raise ValueError('Profile inventory exceeds 256 profiles')
    rows = []
    for name, value in sorted(profiles.items()):
        if not name or len(name) > 256:
            raise ValueError('Profile inventory names require 1 to 256 characters')
        profile = parse(value)
        rows.append({'name': name, 'model': profile.model, 'api': profile.api,
                     'capabilities': sorted(profile.capabilities)})
    result = {'schema_version': 1, 'profiles': rows}
    if len(json.dumps(result, ensure_ascii=True).encode()) > 1024 * 1024:
        raise ValueError('Profile inventory exceeds 1 MiB')
    return result


def main(path: Path | None, format: str) -> int:
    from .diagnostics import locations
    try:
        report = inventory(path or Path(locations(Path.home())['profiles']))
        output = (json.dumps(report, ensure_ascii=True) + '\n' if format == 'json' else
                  ''.join(safe(f"{json.dumps(r['name'], ensure_ascii=True)}: "
                               f"{json.dumps(r['model'], ensure_ascii=True)} ({r['api']}); "
                               f"capabilities={','.join(r['capabilities'])}") + '\n'
                          for r in report['profiles']))
        Streams(time.monotonic() + 5, threading.Event()).write(output)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, RecursionError, TimeoutError):
        from .run_cli import failure
        return failure('text', 0, 'failed', 2,
                       'profile inventory failed; verify the profile configuration.')
