"""Read-only registered launch binding for supervised callers."""
import os
from pathlib import Path

from . import registration_owner as owner
from .profile_setup import _parent, _target
from .registration_plan import command, qualify_dispatcher
from .runtime_install import selected
from .runtime_lock import runtime_use


def resolve(executable: Path, root: Path) -> list[str]:
    """Resolve an owned registration into qualified immutable dispatcher argv.

    Never execute the mutable registration file after checking it. The returned
    dispatcher checks current selection again before routing the command.
    """
    executable, root = _target(executable), _target(root)
    if executable.name != owner.CLI_COMMAND or executable.is_relative_to(root):
        raise ValueError("Expected an external registered command")
    fd = _parent(executable, create=False)
    if fd is None:
        raise FileNotFoundError("Registered command is missing")
    try:
        with runtime_use(executable.parent, timeout=5, create=False):
            if owner._read(fd, owner.PENDING) is not None:
                raise ValueError("Registration has an unresolved operation")
            raw = owner._read(fd, owner.RECEIPT)
            if raw is None:
                raise ValueError("Registered command receipt is missing")
            specification = owner._record(raw, executable)
            if raw != owner.encode({"schema_version": 1, "specification": specification}):
                raise ValueError("Registration receipt is not canonical")
            if specification["runtime_root"] != str(root):
                raise ValueError("Registration belongs to a different runtime root")
            if owner._read(fd, owner.CLI_COMMAND, executable=True) != specification["launcher"].encode():
                raise ValueError("Registered command was modified")
    finally:
        os.close(fd)
    # Never invert runtime-before-bin ordering or retain a parent lease during
    # child dispatch. Selection changes are rechecked by registered_cli.
    with selected(root, timeout=5, create=False) as release:
        if release.name != specification["release"]:
            raise ValueError("Registered command is stale")
        qualify_dispatcher(release)
        return command(root, release.name)
