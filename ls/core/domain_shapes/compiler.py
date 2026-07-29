from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any

from .config import load_domain_shapes
from .models import (
    DomainCompileError,
    DomainDefinition,
    DomainRoot,
    DomainShapesConfig,
    DomainShapesError,
)

_PRIVATE_COMPONENTS = frozenset(
    {
        ".codex",
        ".cache",
        ".git",
        ".herdr",
        ".localsetup",
        ".localsetup-maint",
        ".omp",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
)
_PRIVATE_FILENAMES = (".env", ".env.*", "*.key", "*.pem", "*.p12", "*.pfx", "*.secret", "*.secret.*", "secrets.*")


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    """Encode a JSON payload without whitespace or nondeterministic fields."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class CompileResult(Mapping[str, Any]):
    payload: dict[str, Any]
    canonical_bytes: bytes
    digest: str

    def __getitem__(self, key: str) -> Any:
        return self.payload[key]

    def __iter__(self):
        return iter(self.payload)

    def __len__(self) -> int:
        return len(self.payload)

    @property
    def output_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload)


def _portable_path(path: str) -> str:
    return path.replace("\\", "/")


def _private_reason(relative: str) -> str | None:
    parts = relative.split("/")
    if any(part in _PRIVATE_COMPONENTS for part in parts):
        return "private_runtime"
    if any(_glob_matches(parts[-1], pattern) for pattern in _PRIVATE_FILENAMES):
        return "private_runtime"
    return None


def _glob_parts_match(path: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    if not pattern:
        return not path
    if pattern[0] == "**":
        return any(_glob_parts_match(path[index:], pattern[1:]) for index in range(len(path) + 1))
    return bool(path) and fnmatch.fnmatchcase(path[0], pattern[0]) and _glob_parts_match(path[1:], pattern[1:])


def _glob_matches(relative: str, pattern: str) -> bool:
    normalized = _portable_path(relative)
    normalized_pattern = _portable_path(pattern)
    if "/" not in normalized_pattern:
        return fnmatch.fnmatchcase(Path(normalized).name, normalized_pattern)
    if _glob_parts_match(tuple(normalized.split("/")), tuple(normalized_pattern.split("/"))):
        return True
    if normalized_pattern.startswith("**/") and _glob_parts_match(
        tuple(normalized.split("/")), tuple(normalized_pattern[3:].split("/"))
    ):
        return True
    return False


def _matches(relative: str, globs: tuple[str, ...], regexes: tuple[re.Pattern[str], ...]) -> tuple[bool, str | None]:
    if any(_glob_matches(relative, pattern) for pattern in globs):
        return True, "exclude_glob"
    if any(expression.search(relative) is not None for expression in regexes):
        return True, "exclude_regex"
    return False, None


def _git_ignored(repo_root: Path, relative_paths: Iterable[str]) -> set[str]:
    paths = sorted(set(relative_paths))
    if not paths:
        return set()
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "--stdin", "-z"],
            input=b"\0".join(item.encode("utf-8") for item in paths) + b"\0",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        raise DomainCompileError(
            f"could not determine Git ignore status: {exc}",
            issues=("git ignore status unavailable",),
        ) from exc
    if completed.returncode not in (0, 1):
        raise DomainCompileError(
            "could not determine Git ignore status: git check-ignore failed",
            issues=("git ignore status unavailable",),
        )
    ignored: set[str] = set()
    for item in completed.stdout.split(b"\0"):
        if item:
            try:
                ignored.add(item.decode("utf-8"))
            except UnicodeDecodeError:
                continue
    return ignored


def _assert_no_symlink_components(repo_root: Path, relative: str) -> None:
    current = repo_root
    if relative == ".":
        return
    for component in relative.split("/"):
        current /= component
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return
        except OSError as exc:
            raise DomainCompileError(
                f"could not inspect root path {relative!r}: {exc}",
                issues=(f"could not inspect root path {relative!r}: {exc}",),
            ) from exc
        if stat.S_ISLNK(mode):
            raise DomainCompileError(
                f"domain root {relative!r} contains a symlink component (symlink_root)",
                issues=(f"symlink root: {relative}",),
            )


def _repository_root(directory: Path | str) -> Path:
    supplied = Path(directory).expanduser()
    lexical = Path(os.path.abspath(supplied))
    current = Path(lexical.anchor)
    for component in lexical.parts[1:]:
        current /= component
        try:
            mode = os.lstat(current).st_mode
        except OSError as exc:
            raise DomainCompileError(f"repository directory is unavailable: {lexical}: {exc}") from exc
        if stat.S_ISLNK(mode):
            raise DomainCompileError(
                f"repository directory contains a symlink component: {current}",
                issues=(f"repository directory contains a symlink component: {current}",),
            )
    if not stat.S_ISDIR(os.lstat(lexical).st_mode):
        raise DomainCompileError(
            f"repository directory must be a non-symlink directory: {lexical}",
            issues=(f"invalid repository directory: {lexical}",),
        )
    return lexical


def _content_digest(path: Path, *, max_bytes: int) -> tuple[int, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DomainCompileError(f"could not read selected file safely: {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise DomainCompileError(f"selected path is no longer a regular file: {path}")
        if metadata.st_size > max_bytes:
            raise DomainCompileError(
                f"selected file {path} exceeds remaining max_bytes={max_bytes} (max_bytes)"
            )
        digest = hashlib.sha256()
        bytes_read = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            bytes_read += len(chunk)
            if bytes_read > max_bytes:
                raise DomainCompileError(
                    f"selected file {path} exceeds remaining max_bytes={max_bytes} (max_bytes)"
                )
            digest.update(chunk)
        return bytes_read, digest.hexdigest()
    finally:
        os.close(descriptor)


def _root_absolute(repo_root: Path, root: DomainRoot) -> Path:
    _assert_no_symlink_components(repo_root, root.path)
    if root.path == ".":
        return repo_root
    return repo_root.joinpath(*root.path.split("/"))


def _enumerate_tree(path: Path, relative: str) -> Iterable[tuple[str, Path, int]]:
    try:
        with os.scandir(path) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
            for entry in entries:
                child_relative = entry.name if relative == "." else f"{relative}/{entry.name}"
                child_path = Path(entry.path)
                try:
                    mode = entry.stat(follow_symlinks=False).st_mode
                except OSError as exc:
                    raise DomainCompileError(f"could not inspect domain path {child_relative!r}: {exc}") from exc
                yield child_relative, child_path, mode
                if stat.S_ISDIR(mode) and _private_reason(child_relative) is None:
                    yield from _enumerate_tree(child_path, child_relative)
    except OSError as exc:
        raise DomainCompileError(f"could not enumerate domain path {relative!r}: {exc}") from exc


def _root_entries(repo_root: Path, root: DomainRoot) -> Iterable[tuple[str, Path, int]]:
    path = _root_absolute(repo_root, root)
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError as exc:
        raise DomainCompileError(
            f"domain root {root.path!r} is missing (missing_root)",
            issues=(f"missing root: {root.path}",),
        ) from exc
    except OSError as exc:
        raise DomainCompileError(
            f"could not inspect domain root {root.path!r}: {exc}",
            issues=(f"could not inspect root {root.path!r}: {exc}",),
        ) from exc
    if stat.S_ISLNK(mode):
        raise DomainCompileError(
            f"domain root {root.path!r} is a symlink (symlink_root)",
            issues=(f"symlink root: {root.path}",),
        )
    if root.kind == "file":
        if not stat.S_ISREG(mode):
            raise DomainCompileError(
                f"file root {root.path!r} is not a regular file (root_kind)",
                issues=(f"file root is not a regular file: {root.path}",),
            )
        yield root.path, path, mode
        return
    if not stat.S_ISDIR(mode):
        raise DomainCompileError(
            f"tree root {root.path!r} is not a directory (root_kind)",
            issues=(f"tree root is not a directory: {root.path}",),
        )
    yield from _enumerate_tree(path, root.path)


def _compile_patterns(definition: DomainDefinition) -> tuple[tuple[re.Pattern[str], ...], tuple[re.Pattern[str], ...]]:
    try:
        include_regex = tuple(re.compile(expression) for expression in definition.include.regex)
        exclude_regex = tuple(re.compile(expression) for expression in definition.exclude.regex)
    except re.error as exc:
        raise DomainCompileError(f"domain {definition.domain_id!r} contains invalid regex: {exc}") from exc
    return include_regex, exclude_regex


def _classify(
    relative: str,
    mode: int,
    *,
    ignored: set[str],
    definition: DomainDefinition,
    include_regex: tuple[re.Pattern[str], ...],
    exclude_regex: tuple[re.Pattern[str], ...],
) -> tuple[bool, str | None]:
    private_reason = _private_reason(relative)
    if private_reason is not None:
        return False, private_reason
    if relative in ignored:
        return False, "git_ignored"
    if stat.S_ISLNK(mode):
        return False, "symlink"
    if not stat.S_ISREG(mode):
        return False, "unsupported_type"
    excluded, reason = _matches(relative, definition.exclude.glob, exclude_regex)
    if excluded:
        return False, reason
    if definition.include.empty:
        return True, None
    included = any(_glob_matches(relative, pattern) for pattern in definition.include.glob) or any(
        expression.search(relative) is not None for expression in include_regex
    )
    return (True, None) if included else (False, "not_included")


def compile_domain(
    config: DomainShapesConfig | Path | str,
    domain_id: str,
    directory: Path | str,
    *,
    schema_path: Path | str | None = None,
) -> CompileResult:
    """Compile one domain into a stable, read-only selected/excluded workset."""

    if isinstance(config, DomainShapesConfig):
        loaded = config
    else:
        loaded = load_domain_shapes(config, schema_path=schema_path)
    definition = loaded.domain(domain_id)
    repo_root = _repository_root(directory)
    include_regex, exclude_regex = _compile_patterns(definition)

    discovered: dict[str, tuple[Path, int]] = {}
    for root in definition.roots:
        for relative, absolute, mode in _root_entries(repo_root, root):
            relative = _portable_path(relative)
            discovered.setdefault(relative, (absolute, mode))

    ignored = _git_ignored(repo_root, discovered)
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    selected_bytes = 0
    for relative in sorted(discovered):
        _absolute, mode = discovered[relative]
        is_selected, reason = _classify(
            relative,
            mode,
            ignored=ignored,
            definition=definition,
            include_regex=include_regex,
            exclude_regex=exclude_regex,
        )
        if is_selected:
            if len(selected) >= definition.max_files:
                raise DomainCompileError(
                    f"domain {domain_id!r} exceeds max_files={definition.max_files} (max_files)",
                    issues=(f"max_files exceeded: {len(selected) + 1} > {definition.max_files}",),
                )
            try:
                size, content_digest = _content_digest(
                    discovered[relative][0],
                    max_bytes=definition.max_bytes - selected_bytes,
                )
            except DomainCompileError:
                raise
            selected.append({"path": relative, "size": size, "sha256": content_digest})
            selected_bytes += size
        else:
            if reason in {"private_runtime", "git_ignored"}:
                continue
            excluded.append({"path": relative, "reason": reason or "excluded"})

    selected.sort(key=lambda item: item["path"])
    excluded.sort(key=lambda item: (item["path"], item["reason"]))
    payload_without_digest: dict[str, Any] = {
        "ok": True,
        "schema_version": loaded.schema_version,
        "domain": definition.domain_id,
        "selected": selected,
        "excluded": excluded,
    }
    canonical = canonical_json_bytes(payload_without_digest)
    digest = hashlib.sha256(canonical).hexdigest()
    payload = {**payload_without_digest, "digest": digest}
    return CompileResult(payload=payload, canonical_bytes=canonical, digest=digest)


__all__ = ["CompileResult", "canonical_json_bytes", "compile_domain"]
