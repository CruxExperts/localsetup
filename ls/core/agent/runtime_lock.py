"""Shared runtime use and exclusive upgrade leases on qualified POSIX hosts."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import math
import os
from pathlib import Path
import stat
import time
from typing import Iterator


LOCK_NAME = ".runtime-use.lock"


def _directory(path: Path) -> int:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Runtime root must be an absolute canonical path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError("Runtime root must be user-owned and not writable by other users")
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def runtime_use(root: Path, *, exclusive: bool = False, timeout: float = 30.0, create: bool = True) -> Iterator[None]:
    """Lease an existing runtime root; never delete or replace its lock inode.

    With create=False, take a shared lease on an existing lock without creating
    filesystem state. Missing locks fail for callers to report incomplete setup.

    Callers protect the directory against untrusted same-user processes through
    the sandbox. Acquire the package-root lock first when both are needed.
    """
    if not isinstance(create, bool) or (exclusive and not create):
        raise ValueError("Noncreating runtime leases must be shared")
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("Runtime lock timeout must be finite and nonnegative")
    if os.name != "posix":
        raise RuntimeError("Runtime leases require a qualified POSIX lock backend")
    import fcntl

    deadline = time.monotonic() + timeout
    directory = _directory(root)
    fd = None
    try:
        flags = (os.O_RDWR | os.O_CREAT) if create else os.O_RDONLY
        fd = os.open(LOCK_NAME, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600, dir_fd=directory)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Runtime lock must be a private user-owned regular file with one link")
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        while True:
            try:
                fcntl.flock(fd, operation | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Runtime is in use; lease deadline expired") from exc
                time.sleep(min(0.05, remaining))
        current = os.stat(LOCK_NAME, dir_fd=directory, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("Runtime lock identity changed while waiting")
        yield
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)
