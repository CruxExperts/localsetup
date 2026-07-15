from __future__ import annotations

from dataclasses import dataclass
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


def _path_matches_directory(path: Path, directory_fd: int) -> bool:
    try:
        resolved = path.parent.stat(follow_symlinks=False)
    except OSError:
        return False
    bound = os.fstat(directory_fd)
    return stat.S_ISDIR(resolved.st_mode) and (resolved.st_dev, resolved.st_ino) == (bound.st_dev, bound.st_ino)


def _read_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(fd, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_mutable(details: os.stat_result, *, label: str) -> None:
    if not stat.S_ISREG(details.st_mode) or details.st_uid != os.geteuid() or details.st_nlink != 1:
        raise ClientStateError(f"{label} must be an owned single-link regular file", code="unsafe_exclude")


def _open_mutable_regular(directory_fd: int, name: str, *, append: bool) -> int:
    try:
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            if append:
                flags |= os.O_APPEND
            fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
            before = os.fstat(fd)
            os.fchmod(fd, 0o600)
        except FileExistsError:
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            _validate_mutable(before, label="Git mutable file")
            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | (os.O_APPEND if append else 0)
            fd = os.open(name, flags, dir_fd=directory_fd)
    else:
        _validate_mutable(before, label="Git mutable file")
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | (os.O_APPEND if append else 0)
        fd = os.open(name, flags, dir_fd=directory_fd)
    details = os.fstat(fd)
    try:
        _validate_mutable(details, label="Git mutable file")
        if (before.st_dev, before.st_ino) != (details.st_dev, details.st_ino):
            raise ClientStateError("Git mutable file changed during open", code="unsafe_exclude")
    except Exception:
        os.close(fd)
        raise
    return fd


def _binding_matches(git_root: Path, path: Path, parent_fd: int | None = None) -> bool:
    if _resolved_exclude(git_root) != path:
        return False
    return parent_fd is None or _path_matches_directory(path, parent_fd)


def _rollback_tail(fd: int, owned: bytes) -> bool:
    try:
        current = _read_fd(fd)
        if not current.endswith(owned):
            return False
        os.ftruncate(fd, len(current) - len(owned))
        os.fsync(fd)
        return True
    except OSError:
        return False


def _raise_after_rollback(fd: int, owned: bytes, message: str, code: str) -> None:
    if not _rollback_tail(fd, owned):
        raise ClientStateError("Git exclude commit state is ambiguous", code="exclude_commit_ambiguous")
    raise ClientStateError(message, code=code)


def plan_git_exclude(location: StateLocation) -> ExcludePlan:
    current = refresh_state_location(location, allow_created_roots=True)
    if current.scope != "repo":
        return ExcludePlan("not-applicable", None, None, None)
    assert current.git is not None
    entry = _entry(current)
    path = _resolved_exclude(current.git.root)
    if path != current.git.exclude_path:
        raise ClientStateError("Git exclude binding changed", code="stale_state_binding")
    try:
        parent_fd = _open_directory(path.parent, create=False)
        try:
            if not _path_matches_directory(path, parent_fd):
                raise ClientStateError("Git exclude owner is unsafe", code="unsafe_exclude")
            try:
                before = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                data = b""
            else:
                _validate_mutable(before, label="Git info/exclude")
                fd = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
                try:
                    details = os.fstat(fd)
                    _validate_mutable(details, label="Git info/exclude")
                    if (before.st_dev, before.st_ino) != (details.st_dev, details.st_ino):
                        raise ClientStateError("Git info/exclude changed during open", code="unsafe_exclude")
                    data = _read_fd(fd)
                finally:
                    os.close(fd)
        finally:
            os.close(parent_fd)
        data.decode("utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise ClientStateError("Git info/exclude is unreadable or not UTF-8", code="unsafe_exclude") from exc
    ignored = _effective_ignore(current.git.root, entry)
    after = refresh_state_location(location, allow_created_roots=True)
    if after.git is None or not _binding_matches(current.git.root, path):
        raise ClientStateError("Git exclude binding changed", code="stale_state_binding")
    if ignored:
        return ExcludePlan("already-ignored", entry, path, _digest(data), current.git.root)
    return ExcludePlan("append", entry, path, _digest(data), current.git.root)


def apply_git_exclude(plan: ExcludePlan) -> ExcludePlan:
    if plan.action != "append":
        return plan
    assert plan.exclude_path is not None and plan.entry is not None and plan.git_root is not None
    path = _resolved_exclude(plan.git_root)
    if path != plan.exclude_path:
        raise ClientStateError("Git exclude binding changed", code="stale_state_binding")
    try:
        parent_fd = _open_directory(path.parent, create=True)
    except OSError as exc:
        raise ClientStateError("Git exclude owner is unsafe", code="unsafe_exclude") from exc
    try:
        if not _path_matches_directory(path, parent_fd):
            raise ClientStateError("Git exclude owner is unsafe", code="unsafe_exclude")
        lock_name = f"{path.name}.localsetup.lock"
        lock_fd = _open_mutable_regular(parent_fd, lock_name, append=False)
        try:
            os.fchmod(lock_fd, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ClientStateError("another client-state exclude update is in progress", code="exclude_locked") from exc
            if not _binding_matches(plan.git_root, path, parent_fd):
                raise ClientStateError("Git exclude binding changed", code="stale_state_binding")
            try:
                fd = _open_mutable_regular(parent_fd, path.name, append=True)
            except OSError as exc:
                raise ClientStateError("Git info/exclude is unsafe or unavailable", code="unsafe_exclude") from exc
            try:
                details = os.fstat(fd)
                _validate_mutable(details, label="Git info/exclude")
                current = _read_fd(fd)
                try:
                    current.decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise ClientStateError("Git info/exclude is not UTF-8", code="unsafe_exclude") from exc
                ignored = _effective_ignore(plan.git_root, plan.entry)
                if not _binding_matches(plan.git_root, path, parent_fd):
                    raise ClientStateError("Git exclude binding changed", code="stale_state_binding")
                if ignored:
                    return ExcludePlan("already-ignored", plan.entry, path, _digest(current), plan.git_root)
                newline = b"\r\n" if b"\r\n" in current and b"\n" not in current.replace(b"\r\n", b"") else b"\n"
                separator = b"" if not current or current.endswith((b"\n", b"\r")) else newline
                owned = separator + plan.entry.encode("utf-8") + newline
                written = os.write(fd, owned)
                if written != len(owned):
                    partial = owned[: max(written, 0)]
                    _raise_after_rollback(fd, partial, "Git info/exclude append was incomplete", "exclude_write_failed")
                try:
                    os.fsync(fd)
                except OSError:
                    _raise_after_rollback(fd, owned, "Git info/exclude append was not durable", "exclude_write_failed")
                if not _binding_matches(plan.git_root, path, parent_fd):
                    _raise_after_rollback(fd, owned, "Git exclude binding changed", "stale_state_binding")
                ignored = _effective_ignore(plan.git_root, plan.entry)
                if not _binding_matches(plan.git_root, path, parent_fd):
                    _raise_after_rollback(fd, owned, "Git exclude binding changed", "stale_state_binding")
                if not ignored:
                    _raise_after_rollback(fd, owned, "Git info/exclude update was ineffective", "exclude_verify_failed")
                final = _read_fd(fd)
                return ExcludePlan("applied", plan.entry, path, _digest(final), plan.git_root)
            finally:
                os.close(fd)
        finally:
            os.close(lock_fd)
    finally:
        os.close(parent_fd)
