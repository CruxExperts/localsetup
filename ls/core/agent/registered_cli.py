"""Release-bound installed dispatcher; registration file ownership is separate."""
from pathlib import Path
import sys
import threading
import time

from ..branding import CLI_NAME
from .runtime_install import DIGEST, selected
from .run_io import Streams


def _origin(release: Path) -> None:
    expected = release / 'venv/lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages/ls/core/agent/registered_cli.py'
    if (Path(sys.executable).absolute() != release / 'venv/bin/python'
            or Path(__file__).absolute() != expected
            or not expected.is_relative_to(release / 'venv')):
        raise ValueError('Registration must dispatch from its protected installed release')


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(arguments) < 2 or not DIGEST.fullmatch(arguments[1]):
            raise ValueError('Registration requires an explicit release identity')
        root, digest = Path(arguments[0]), arguments[1]
        if not root.is_absolute() or '..' in root.parts:
            raise ValueError('Registration runtime root must be canonical')
        with selected(root, timeout=5, create=False) as release:
            if release.name != digest:
                raise ValueError('Registered release differs from current selection')
            _origin(release)
        # Setup needs an exclusive lease; never retain this reader across main.
        from .cli import main as dispatch
        return dispatch(arguments[2:], default_runtime_root=root)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, RuntimeError, RecursionError):
        try:
            Streams(time.monotonic() + 5, threading.Event(), output_fd=2).write(
                f'{CLI_NAME} registration is unavailable or stale; inspect the installed runtime. '
                'Use the verified selected release entrypoint directly for recovery and registration refresh.\n')
        except (OSError, ValueError):
            pass
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
