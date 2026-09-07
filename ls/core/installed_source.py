"""Distinguish installed wheel resources from an editable framework checkout."""
import json
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from .branding import FRAMEWORK_COMMAND


def wheel_module(module: Path) -> bool:
    """Require this module to be an actual recorded distribution file."""
    try:
        installed = distribution(FRAMEWORK_COMMAND)
    except PackageNotFoundError:
        return False
    if not installed.read_text('RECORD') or not installed.read_text('WHEEL'):
        return False
    direct = installed.read_text('direct_url.json')
    if direct and json.loads(direct).get('dir_info', {}).get('editable') is True:
        return False
    return any(str(entry) == 'ls/core/cli.py' and Path(installed.locate_file(entry)).resolve() == module.resolve()
               for entry in installed.files or ())
