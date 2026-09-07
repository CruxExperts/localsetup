"""Provider-free fresh registration command boundary."""
import json
from pathlib import Path
import threading
import time

from ..branding import CLI_NAME
from .diagnostics import locations
from . import registration_owner
from .run_io import Streams


def main(args) -> int:
    try:
        if args.registration_status:
            result = {'schema_version': 1, **registration_owner.status(args.bin_dir)}
            code = 0 if result['status'] == 'registered' else 3
        elif args.refresh_registration or args.recover_registration:
            from . import registration_refresh
            planner = registration_refresh.recovery_plan if args.recover_registration else registration_refresh.plan
            apply = registration_refresh.recover if args.recover_registration else registration_refresh.apply
            result = apply(args.bin_dir, args.registration_sha256) if args.apply else planner(args.bin_dir)
            code = 0
        else:
            root = args.runtime_root or Path(locations(Path.home())['runtimes'])
            result = (registration_owner.apply(root, args.bin_dir, args.registration_sha256) if args.apply
                      else registration_owner.plan(root, args.bin_dir))
            code = 0
        Streams(time.monotonic() + 5, threading.Event()).write(json.dumps(result, ensure_ascii=True) + '\n')
        return code
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, RuntimeError, RecursionError):
        try:
            Streams(time.monotonic() + 5, threading.Event(), output_fd=2).write(
                f'{CLI_NAME} registration failed; inspect the planned digest, PATH, runtime and target records. '
                'After an interrupted apply, inspect pending evidence before recovery; do not replay uncertain writes.\n')
        except (OSError, ValueError):
            pass
        return 2
