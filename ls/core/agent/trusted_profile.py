"""Bounded POSIX reads of configuration that selects credential destinations."""
import os
from pathlib import Path
import stat


def read(path: Path) -> bytes:
    """Anchor the selected path and verify integrity, without requiring secrecy."""
    if os.name != 'posix':
        raise ValueError('Trusted provider configuration requires POSIX ownership checks')
    path = path.absolute()
    if '..' in path.parts or len(path.parts) > 128 or not path.name:
        raise ValueError('Provider configuration path must be canonical and bounded')
    trusted = {0, os.getuid()}
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory = os.open(path.anchor, flags)
    source = None
    try:
        for part in (*path.parts[1:-1], None):
            info = os.fstat(directory)
            sticky_system = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if info.st_uid not in trusted or (info.st_mode & 0o022 and not sticky_system):
                raise ValueError('Provider configuration ancestor has unsafe ownership or permissions')
            if part is not None:
                child = os.open(part, flags, dir_fd=directory)
                os.close(directory)
                directory = child
        source = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=directory)
        info = os.fstat(source)
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in trusted or info.st_mode & 0o022:
            raise ValueError('Provider configuration must be a trusted regular file without other-user write access')
        with os.fdopen(source, 'rb') as stream:
            source = None
            return stream.read(1024 * 1024 + 1)
    finally:
        if source is not None:
            os.close(source)
        os.close(directory)
