"""Read-only fresh PATH registration specifications for protected LSCli."""
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import sys

from ..branding import CLI_COMMAND
from .profile_setup import _absent, _parent, _target
from .runtime_install import selected


def launcher(root: Path, digest: str) -> bytes:
    executable = root / digest / 'venv/bin/python'
    command = [str(executable), '-I', '-B', '-m', 'ls.core.agent.registered_cli', str(root), digest]
    return ('#!/bin/sh\nexec ' + ' '.join(shlex.quote(part) for part in command) + ' "$@"\n').encode()


def path_check(bin_dir: Path, path_env: str) -> dict:
    if len(path_env.encode()) > 64 * 1024:
        raise ValueError('PATH exceeds registration inspection bounds')
    entries = path_env.split(os.pathsep)
    if len(entries) > 256:
        raise ValueError('PATH has too many entries')
    normalized = [Path(os.path.abspath(entry)) for entry in entries]
    try:
        position = normalized.index(bin_dir)
    except ValueError:
        return {'on_path': False, 'ready': False, 'reason': 'bin_directory_not_on_path'}
    for entry in normalized[:position]:
        if shutil.which(CLI_COMMAND, path=str(entry)) is not None:
            raise FileExistsError('An earlier PATH command would shadow the registration')
    return {'on_path': True, 'ready': True, 'reason': None}


def plan(root: Path, bin_dir: Path, *, path_env: str | None = None) -> dict:
    root = _target(root)
    target = _target(bin_dir / CLI_COMMAND)
    if target.is_relative_to(root):
        raise ValueError('PATH registration must remain outside the protected runtime tree')
    parent = _parent(target, create=False)
    if parent is not None:
        try:
            _absent(parent, target.name)
        finally:
            os.close(parent)
    location = path_check(target.parent, os.environ.get('PATH', '') if path_env is None else path_env)
    with selected(root, timeout=5, create=False) as release:
        module = release / 'venv/lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages/ls/core/agent/registered_cli.py'
        # The current planner qualifies precisely its installed dispatcher contract.
        # A different release must use its own planner; never execute it to inspect it.
        expected = Path(__file__).with_name('registered_cli.py').read_bytes()
        if module.is_symlink() or not module.is_file() or module.stat().st_size != len(expected) or module.read_bytes() != expected:
            raise ValueError('Selected release does not contain the qualified registration dispatcher')
        content = launcher(root, release.name)
        return {'schema_version': 1, 'operation': 'register_command', 'command': CLI_COMMAND,
                'target': str(target), 'runtime_root': str(root), 'release': release.name,
                'expected_target': 'absent', 'launcher_sha256': hashlib.sha256(content).hexdigest(),
                'launcher': content.decode(), 'path': location}
