from __future__ import annotations

from dataclasses import dataclass, field, replace
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import subprocess

from .locator import _required_git_path, git_environment, refresh_state_location
from .models import ClientStateError, StateLocation


_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


@dataclass(frozen=True)
class ExcludePlan:
    action: str
    entry: str | None
    exclude_path: Path | None
    expected_digest: str | None
    git_root: Path | None = None
    repo_root_device: int | None = field(default=None, repr=False)
    repo_root_inode: int | None = field(default=None, repr=False)
    exclude_parent_device: int | None = field(default=None, repr=False)
    exclude_parent_inode: int | None = field(default=None, repr=False)
    exclude_present: bool | None = field(default=None, repr=False)
    exclude_device: int | None = field(default=None, repr=False)
    exclude_inode: int | None = field(default=None, repr=False)

    def payload(self) -> dict[str, str | None]:
        return {"action": self.action, "entry": self.entry}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(location: StateLocation) -> str:
    if location.scope != "repo" or location.git is None:
        raise ClientStateError("Git exclude is available only for repo-scoped state", code="exclude_not_applicable")
    relative = location.root.relative_to(location.git.root).as_posix()
    return f"/{relative.rstrip('/')}/"


def _effective_ignore(git_root: Path, entry: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(git_root), "check-ignore", "--quiet", "--no-index", entry.lstrip("/")],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=git_environment(),
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise ClientStateError("Git ignore verification failed", code="git_ignore_probe_failed")


def _resolved_exclude(git_root: Path) -> Path:
    try:
        value = _required_git_path(
            git_root, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"
        )
    except ClientStateError as exc:
        raise ClientStateError("Git exclude resolution failed", code="git_ignore_probe_failed") from exc
    return Path(value)


def _open_directory(path: Path, *, create: bool) -> int:
    if not path.is_absolute():
        raise ClientStateError("Git exclude owner is unsafe", code="unsafe_exclude")
    fd = os.open("/", _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            try:
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=fd)
                os.chmod(part, 0o700, dir_fd=fd, follow_symlinks=False)
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
                os.fchmod(next_fd, 0o700)
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def _open_bound_directories(root: Path, parent: Path) -> tuple[int, int]:
    root_fd = _open_directory(root, create=False)
    try:
        parent_fd = _open_directory(parent, create=False)
    except Exception:
        os.close(root_fd)
        raise
    return root_fd, parent_fd


def _path_matches_fd(path: Path, fd: int) -> bool:
    try:
        current = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ClientStateError("Git exclude binding is unsafe or unavailable", code="unsafe_exclude") from exc
    try:
        held = os.fstat(fd)
    except OSError as exc:
        raise ClientStateError("Git exclude binding is unsafe or unavailable", code="unsafe_exclude") from exc
    return (current.st_dev, current.st_ino) == (held.st_dev, held.st_ino)


def _read_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(fd, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def _require_utf8(data: bytes) -> None:
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ClientStateError("Git info/exclude is not UTF-8", code="unsafe_exclude") from exc


def _validate_mutable(details: os.stat_result, *, label: str) -> None:
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.geteuid()
        or details.st_nlink != 1
        or details.st_mode & 0o022 != 0
    ):
        raise ClientStateError(f"{label} must be an owned single-link regular file", code="unsafe_exclude")


def _open_mutable_regular(directory_fd: int, name: str, *, append: bool) -> int:
    label = "Git mutable file"
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | (os.O_APPEND if append else 0)

    def open_existing(before: os.stat_result) -> int:
        _validate_mutable(before, label=label)
        try:
            fd = os.open(name, flags, dir_fd=directory_fd)
        except FileNotFoundError as exc:
            raise ClientStateError("Git mutable file binding changed", code="stale_state_binding") from exc
        except OSError as exc:
            raise ClientStateError("Git mutable file is unsafe or unavailable", code="unsafe_exclude") from exc
        try:
            details = os.fstat(fd)
            _validate_mutable(details, label=label)
            if _identity(before) != _identity(details):
                raise ClientStateError("Git mutable file binding changed", code="stale_state_binding")
            _require_entry_binding(directory_fd, name, fd, label=label)
            return fd
        except ClientStateError:
            os.close(fd)
            raise
        except OSError as exc:
            os.close(fd)
            raise ClientStateError("Git mutable file is unsafe or unavailable", code="unsafe_exclude") from exc

    try:
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        try:
            fd = os.open(
                name,
                flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            try:
                before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise ClientStateError(
                    "Git mutable file binding changed", code="stale_state_binding"
                ) from exc
            except OSError as exc:
                raise ClientStateError(
                    "Git mutable file is unsafe or unavailable", code="unsafe_exclude"
                ) from exc
            return open_existing(before)
        except OSError as exc:
            raise ClientStateError(
                "Git mutable file is unsafe or unavailable", code="unsafe_exclude"
            ) from exc
        try:
            os.fchmod(fd, 0o600)
            details = os.fstat(fd)
            _validate_mutable(details, label=label)
            _require_entry_binding(directory_fd, name, fd, label=label)
            return fd
        except ClientStateError:
            os.close(fd)
            raise
        except OSError as exc:
            os.close(fd)
            raise ClientStateError(
                "Git mutable file is unsafe or unavailable", code="unsafe_exclude"
            ) from exc
    except OSError as exc:
        raise ClientStateError(
            "Git mutable file is unsafe or unavailable", code="unsafe_exclude"
        ) from exc
    return open_existing(before)


def _identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


def _require_append_tokens(plan: ExcludePlan) -> None:
    required = (
        plan.repo_root_device,
        plan.repo_root_inode,
        plan.exclude_parent_device,
        plan.exclude_parent_inode,
        plan.exclude_present,
    )
    if any(value is None for value in required):
        raise ClientStateError("Git exclude plan is missing identity bindings", code="stale_state_binding")
    if plan.exclude_present and (plan.exclude_device is None or plan.exclude_inode is None):
        raise ClientStateError("Git exclude plan is missing identity bindings", code="stale_state_binding")
    if not plan.exclude_present and (plan.exclude_device is not None or plan.exclude_inode is not None):
        raise ClientStateError("Git exclude plan has inconsistent identity bindings", code="stale_state_binding")


def _require_base_bindings(
    plan: ExcludePlan,
    path: Path,
    root_fd: int,
    parent_fd: int,
) -> None:
    assert plan.git_root is not None
    root_details = os.fstat(root_fd)
    parent_details = os.fstat(parent_fd)
    if (
        not _path_matches_fd(plan.git_root, root_fd)
        or _identity(root_details) != (plan.repo_root_device, plan.repo_root_inode)
        or not _path_matches_fd(path.parent, parent_fd)
        or _identity(parent_details) != (plan.exclude_parent_device, plan.exclude_parent_inode)
    ):
        raise ClientStateError("Git exclude binding changed", code="stale_state_binding")
    if _resolved_exclude(plan.git_root) != path:
        try:
            current = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            current = None
        except OSError as exc:
            raise ClientStateError(
                "Git info/exclude is unsafe or unavailable", code="unsafe_exclude"
            ) from exc
        if current is not None and not stat.S_ISREG(current.st_mode):
            raise ClientStateError(
                "Git info/exclude must be a regular file", code="unsafe_exclude"
            )
        raise ClientStateError("Git exclude binding changed", code="stale_state_binding")


def _require_entry_binding(parent_fd: int, name: str, fd: int, *, label: str) -> None:
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ClientStateError(f"{label} binding changed", code="stale_state_binding") from exc
    except OSError as exc:
        raise ClientStateError(f"{label} is unsafe or unavailable", code="unsafe_exclude") from exc
    try:
        held = os.fstat(fd)
    except OSError as exc:
        raise ClientStateError(f"{label} is unsafe or unavailable", code="unsafe_exclude") from exc
    if _identity(current) != _identity(held):
        raise ClientStateError(f"{label} binding changed", code="stale_state_binding")
    _validate_mutable(held, label=label)


def _require_absent(parent_fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ClientStateError("Git info/exclude is unsafe or unavailable", code="unsafe_exclude") from exc
    raise ClientStateError("Git info/exclude appeared after planning", code="stale_state_binding")


def _create_mutable_regular_exclusive(directory_fd: int, name: str, *, append: bool) -> int:
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    if append:
        flags |= os.O_APPEND
    try:
        return os.open(name, flags, 0o600, dir_fd=directory_fd)
    except FileExistsError as exc:
        raise ClientStateError("Git info/exclude appeared after planning", code="stale_state_binding") from exc
    except OSError as exc:
        raise ClientStateError("Git info/exclude is unsafe or unavailable", code="unsafe_exclude") from exc


def _raise_ambiguous(cause: BaseException | None = None) -> None:
    error = ClientStateError(
        "Git exclude commit state is ambiguous", code="exclude_commit_ambiguous"
    )
    if cause is None:
        raise error
    raise error from cause


def plan_git_exclude(location: StateLocation) -> ExcludePlan:
    current = refresh_state_location(location, allow_created_roots=True)
    if current.scope != "repo":
        return ExcludePlan("not-applicable", None, None, None)
    assert current.git is not None
    entry = _entry(current)
    path = current.git.exclude_path
    try:
        root_fd, parent_fd = _open_bound_directories(current.git.root, path.parent)
        try:
            root_details = os.fstat(root_fd)
            parent_details = os.fstat(parent_fd)
            if _resolved_exclude(current.git.root) != path:
                raise ClientStateError("Git exclude binding changed", code="stale_state_binding")
            if not _path_matches_fd(current.git.root, root_fd) or not _path_matches_fd(path.parent, parent_fd):
                raise ClientStateError("Git exclude binding changed", code="stale_state_binding")
            exclude_fd: int | None = None
            try:
                try:
                    before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    exclude_present = False
                    exclude_identity = (None, None)
                    data = b""
                else:
                    exclude_present = True
                    _validate_mutable(before, label="Git info/exclude")
                    exclude_fd = os.open(
                        path.name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=parent_fd,
                    )
                    details = os.fstat(exclude_fd)
                    _validate_mutable(details, label="Git info/exclude")
                    if _identity(before) != _identity(details):
                        raise ClientStateError("Git info/exclude changed during open", code="stale_state_binding")
                    exclude_identity = _identity(details)
                    _require_entry_binding(parent_fd, path.name, exclude_fd, label="Git info/exclude")
                    data = _read_fd(exclude_fd)
                    _require_entry_binding(parent_fd, path.name, exclude_fd, label="Git info/exclude")
                plan = ExcludePlan(
                    "append",
                    entry,
                    path,
                    _digest(data),
                    current.git.root,
                    *_identity(root_details),
                    *_identity(parent_details),
                    exclude_present,
                    *exclude_identity,
                )
                _require_base_bindings(plan, path, root_fd, parent_fd)
                if exclude_fd is None:
                    _require_absent(parent_fd, path.name)
                else:
                    _require_entry_binding(parent_fd, path.name, exclude_fd, label="Git info/exclude")
                _require_utf8(data)
                ignored = _effective_ignore(current.git.root, entry)
                after = refresh_state_location(location, allow_created_roots=True)
                if after.git is None:
                    raise ClientStateError("Git exclude binding changed", code="stale_state_binding")
                _require_base_bindings(plan, path, root_fd, parent_fd)
                if exclude_fd is None:
                    _require_absent(parent_fd, path.name)
                else:
                    _require_entry_binding(parent_fd, path.name, exclude_fd, label="Git info/exclude")
                    data = _read_fd(exclude_fd)
                    _require_utf8(data)
                    _require_base_bindings(plan, path, root_fd, parent_fd)
                    _require_entry_binding(
                        parent_fd, path.name, exclude_fd, label="Git info/exclude"
                    )
            finally:
                if exclude_fd is not None:
                    os.close(exclude_fd)
        finally:
            os.close(parent_fd)
            os.close(root_fd)
    except (OSError, UnicodeError) as exc:
        raise ClientStateError("Git info/exclude is unreadable or not UTF-8", code="unsafe_exclude") from exc
    return replace(
        plan,
        action="already-ignored" if ignored else "append",
        expected_digest=_digest(data),
    )


def apply_git_exclude(plan: ExcludePlan) -> ExcludePlan:
    if plan.action != "append":
        return plan
    if plan.exclude_path is None or plan.entry is None or plan.git_root is None:
        raise ClientStateError("Git exclude plan is incomplete", code="stale_state_binding")
    _require_append_tokens(plan)
    path = plan.exclude_path
    try:
        root_fd, parent_fd = _open_bound_directories(plan.git_root, path.parent)
    except OSError as exc:
        raise ClientStateError("Git exclude owner is unsafe", code="unsafe_exclude") from exc
    exclude_fd: int | None = None
    lock_fd: int | None = None
    created_exclude = False
    write_started = False
    lock_name = f"{path.name}.localsetup.lock"
    try:
        _require_base_bindings(plan, path, root_fd, parent_fd)
        if plan.exclude_present:
            try:
                before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise ClientStateError(
                    "Git info/exclude binding changed", code="stale_state_binding"
                ) from exc
            except OSError as exc:
                raise ClientStateError(
                    "Git info/exclude is unsafe or unavailable", code="unsafe_exclude"
                ) from exc
            _validate_mutable(before, label="Git info/exclude")
            if _identity(before) != (plan.exclude_device, plan.exclude_inode):
                raise ClientStateError("Git info/exclude binding changed", code="stale_state_binding")
            try:
                exclude_fd = os.open(
                    path.name,
                    os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_fd,
                )
            except FileNotFoundError as exc:
                raise ClientStateError("Git info/exclude binding changed", code="stale_state_binding") from exc
            except OSError as exc:
                raise ClientStateError(
                    "Git info/exclude is unsafe or unavailable", code="unsafe_exclude"
                ) from exc
            _require_entry_binding(parent_fd, path.name, exclude_fd, label="Git info/exclude")
            if _identity(os.fstat(exclude_fd)) != (plan.exclude_device, plan.exclude_inode):
                raise ClientStateError("Git info/exclude binding changed", code="stale_state_binding")
        else:
            _require_absent(parent_fd, path.name)

        lock_fd = _open_mutable_regular(parent_fd, lock_name, append=False)
        try:
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ClientStateError("another client-state exclude update is in progress", code="exclude_locked") from exc
        except OSError as exc:
            raise ClientStateError("Git exclude lock is unsafe or unavailable", code="unsafe_exclude") from exc

        def require_live() -> None:
            _require_base_bindings(plan, path, root_fd, parent_fd)
            assert lock_fd is not None
            _require_entry_binding(parent_fd, lock_name, lock_fd, label="Git exclude lock")
            if exclude_fd is None:
                _require_absent(parent_fd, path.name)
            else:
                _require_entry_binding(parent_fd, path.name, exclude_fd, label="Git info/exclude")

        require_live()
        if exclude_fd is None:
            ignored = _effective_ignore(plan.git_root, plan.entry)
            require_live()
            if ignored:
                return replace(
                    plan,
                    action="already-ignored",
                    expected_digest=_digest(b""),
                )
            exclude_fd = _create_mutable_regular_exclusive(parent_fd, path.name, append=True)
            created_exclude = True
            os.fchmod(exclude_fd, 0o600)
            _require_entry_binding(parent_fd, path.name, exclude_fd, label="Git info/exclude")
            require_live()
            current = _read_fd(exclude_fd)
            _require_utf8(current)
            require_live()
        else:
            current = _read_fd(exclude_fd)
            _require_utf8(current)
            require_live()
            ignored = _effective_ignore(plan.git_root, plan.entry)
            require_live()
            if ignored:
                final = _read_fd(exclude_fd)
                _require_utf8(final)
                require_live()
                return replace(plan, action="already-ignored", expected_digest=_digest(final))
        newline = b"\r\n" if b"\r\n" in current and b"\n" not in current.replace(b"\r\n", b"") else b"\n"
        separator = b"" if not current or current.endswith((b"\n", b"\r")) else newline
        owned = separator + plan.entry.encode("utf-8") + newline
        write_started = True
        try:
            written = os.write(exclude_fd, owned)
        except OSError as exc:
            raise ClientStateError(
                "Git info/exclude append state is uncertain", code="exclude_commit_ambiguous"
            ) from exc
        if written != len(owned):
            raise ClientStateError(
                "Git info/exclude append was incomplete", code="exclude_write_failed"
            )
        try:
            os.fsync(exclude_fd)
        except OSError as exc:
            raise ClientStateError(
                "Git info/exclude append was not durable", code="exclude_write_failed"
            ) from exc

        require_live()
        ignored = _effective_ignore(plan.git_root, plan.entry)
        require_live()
        if not ignored:
            raise ClientStateError(
                "Git info/exclude update was ineffective", code="exclude_verify_failed"
            )
        final = _read_fd(exclude_fd)
        _require_utf8(final)
        require_live()
        if created_exclude:
            try:
                os.fsync(parent_fd)
            except OSError as exc:
                raise ClientStateError(
                    "Git info/exclude creation durability is uncertain",
                    code="exclude_commit_ambiguous",
                ) from exc
            require_live()
        return replace(plan, action="applied", expected_digest=_digest(final))
    except ClientStateError as exc:
        if created_exclude or write_started:
            _raise_ambiguous(exc)
        raise
    except OSError as exc:
        if created_exclude or write_started:
            _raise_ambiguous(exc)
        raise ClientStateError(
            "Git info/exclude is unsafe or unavailable", code="unsafe_exclude"
        ) from exc
    finally:
        if exclude_fd is not None:
            os.close(exclude_fd)
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(parent_fd)
        os.close(root_fd)
