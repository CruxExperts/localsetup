"""Task-bound Linux sandbox invocations over private, broker-prepared snapshots."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import stat
import threading
import time
from types import MappingProxyType
from typing import Mapping

from .file_grants import PROTECTED
from .native_bundle import _platform
from .runtime_install import selected


@dataclass(frozen=True)
class ProcessGrant:
    task: str
    session: str
    staging: Path
    command: tuple[str, ...]
    expires: float
    disclose_output: bool = False
    revoked: threading.Event = field(default_factory=threading.Event, compare=False, repr=False)

    def __post_init__(self):
        if (not isinstance(self.task, str) or not self.task or not isinstance(self.session, str) or not self.session
                or not self.staging.is_absolute() or '..' in self.staging.parts or not math.isfinite(self.expires)
                or type(self.disclose_output) is not bool):
            raise ValueError('Process grant requires explicit identity, staging root and deadline')
        if (not isinstance(self.command, tuple) or not self.command or len(self.command) > 256
                or any(not isinstance(x, str) or '\x00' in x for x in self.command)
                or sum(len(x.encode()) for x in self.command) > 16384):
            raise ValueError('Process command must be a bounded immutable argument tuple')
        executable = Path(self.command[0])
        if executable.parent != Path('/usr/bin') or str(executable) != self.command[0]:
            raise ValueError('Process executable must be an explicit system tool under /usr/bin')

    def check(self, task: str, session: str) -> None:
        if task != self.task or session != self.session or self.revoked.is_set() or time.monotonic() >= self.expires:
            raise PermissionError('Process grant is mismatched, revoked or expired')


@dataclass(frozen=True)
class Invocation:
    command: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]


def _system_boundary(runtimes: Path) -> None:
    runtimes = runtimes.resolve(strict=True)
    if runtimes.is_relative_to('/usr') or Path('/usr').is_relative_to(runtimes):
        raise ValueError('Runtime must be outside the exposed system toolchain')


def _snapshot(root: Path, runtimes: Path) -> None:
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('Snapshot paths cannot contain symlinks')
    root = root.resolve(strict=True)
    runtimes = runtimes.resolve(strict=True)
    if any(root.is_relative_to(p) or p.is_relative_to(root) for p in (runtimes, Path('/usr'))):
        raise ValueError('Snapshot must be separate from runtime and system toolchain')
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('Snapshot root must be a private owned directory')
    count, size = 0, 0
    def fail(error):
        raise error
    for directory, names, files in os.walk(root, followlinks=False, onerror=fail):
        for name in (*names, *files):
            count += 1
            entry = Path(directory) / name
            info = entry.lstat()
            if name in PROTECTED or name.startswith('.env.') or name == 'AGENTS.md':
                raise ValueError('Snapshot contains protected context or private state')
            if (info.st_uid != os.getuid() or info.st_mode & 0o7022
                    or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                raise ValueError('Snapshot requires owned regular files and directories without shared writes')
            if stat.S_ISREG(info.st_mode):
                size += info.st_size
            if count > 30000 or size > 256 * 1024 * 1024:
                raise ValueError('Snapshot inventory exceeds process limits')


@contextmanager
def invocation(runtimes: Path, grant: ProcessGrant, *, task: str, session: str):
    """Hold the selected runtime lease until the caller has reaped its process tree.

    Caller exclusively owns the snapshot and must enforce cancellation/deadlines
    while running, then authorize disclosure and journal any workspace writeback.
    """
    grant.check(task, session)
    _platform()
    with selected(runtimes, timeout=max(0, grant.expires - time.monotonic())) as release:
        _system_boundary(runtimes)
        binary = release / 'venv' / 'lscli-native' / 'bwrap'
        if not binary.is_file() or binary.is_symlink() or not os.access(binary, os.X_OK):
            raise RuntimeError('Selected runtime has no sealed executable sandbox bundle')
        _snapshot(grant.staging, runtimes)
        grant.check(task, session)
        command = [str(binary), '--unshare-all', '--unshare-user', '--disable-userns', '--die-with-parent', '--new-session',
                   '--cap-drop', 'ALL', '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
                   '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
                   '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                   '--bind', str(grant.staging), '/work', '--chdir', '/work', '--clearenv',
                   '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'HOME', '/tmp',
                   '--setenv', 'LANG', 'C.UTF-8', '--', *grant.command]
        yield Invocation(tuple(command), release, MappingProxyType({'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}))
