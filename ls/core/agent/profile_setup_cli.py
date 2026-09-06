"""Provider-free profile setup command output and defaults."""
import json
from pathlib import Path
import threading
import time

from ..branding import CLI_NAME
from .diagnostics import locations
from . import profile_setup
from .run_io import Streams


def main(args) -> int:
    try:
        target = args.profiles or Path(locations(Path.home())['profiles'])
        result = (profile_setup.apply(args.profile_input, target, args.profile_sha256) if args.apply
                  else profile_setup.plan(args.profile_input, target))
        Streams(time.monotonic() + 5, threading.Event()).write(json.dumps(result, ensure_ascii=True) + '\n')
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, RuntimeError, RecursionError):
        try:
            Streams(time.monotonic() + 5, threading.Event(), output_fd=2).write(
                f'{CLI_NAME} profile setup failed; inspect the input, planned digest and target. '
                'If apply was interrupted, inspect target contents before retrying; existing files are never overwritten.\n')
        except (OSError, ValueError):
            pass
        return 2
