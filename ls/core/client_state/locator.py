from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import hashlib
import json
from collections.abc import Mapping

from ..client_registry import ClientRegistryError, load_client_registry
from .models import ClientStateError, GitContext, StateLocation


_NOT_REPOSITORY = ("not a git repository", "outside repository")


def git_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["LC_ALL"] = "C"
    environment["LANG"] = "C"
    return environment


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=git_environment(),
    )


def _required_git(cwd: Path, *args: str) -> str:
    result = _git(cwd, *args)
    if result.returncode != 0:
        raise ClientStateError("Git state probe failed", code="git_probe_failed")
    value = result.stdout.strip()
    if not value:
        raise ClientStateError("Git state probe returned no value", code="git_probe_failed")
    return value


def probe_git_context(cwd: Path) -> GitContext | None:
    cwd = cwd.expanduser().resolve(strict=True)
    if not cwd.is_dir():
        raise ClientStateError("state probe directory is not a directory", code="invalid_directory")
    inside = _git(cwd, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0:
        detail = (inside.stderr or inside.stdout).lower()
        if any(marker in detail for marker in _NOT_REPOSITORY):
            return None
        raise ClientStateError("ambiguous Git worktree probe failure", code="git_probe_failed")
    if inside.stdout.strip() != "true":
        bare = _git(cwd, "rev-parse", "--is-bare-repository")
        if bare.returncode == 0 and bare.stdout.strip() == "true":
            raise ClientStateError("bare repositories do not have repo-scoped client state")
        raise ClientStateError("Git reports a repository but not a supported worktree")

    root = Path(_required_git(cwd, "rev-parse", "--show-toplevel")).resolve(strict=True)
    exclude = Path(
        _required_git(cwd, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")
    )
    head_result = _git(cwd, "rev-parse", "--verify", "HEAD")
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    ref_result = _git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD")
    ref = ref_result.stdout.strip() if ref_result.returncode == 0 else None
    return GitContext(root=root, exclude_path=exclude, head=head, ref=ref)


def _assert_no_symlink(anchor: Path, target: Path) -> None:
    try:
        relative = target.relative_to(anchor)
    except ValueError as exc:
        raise ClientStateError("client state escapes its owning root") from exc
    current = anchor
    if current.is_symlink():
        raise ClientStateError("client state owner must not be a symlink", code="unsafe_state_path")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ClientStateError("client state path must not traverse a symlink", code="unsafe_state_path")


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        result = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    return (result.st_dev, result.st_ino)


def _global_path(raw: str, *, home: Path) -> tuple[Path, str, Path]:
    if raw == "$CODEX_HOME" or raw.startswith("$CODEX_HOME/"):
        owner = Path(os.path.abspath(Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).expanduser()))
        suffix = raw.removeprefix("$CODEX_HOME").lstrip("/")
        target = owner / suffix
    elif raw == "~" or raw.startswith("~/"):
        owner = Path(os.path.abspath(home))
        target = home / raw.removeprefix("~/") if raw != "~" else home
    else:
        raise ClientStateError("global client state must be home- or CODEX_HOME-scoped")
    target = Path(os.path.abspath(target))
    _assert_no_symlink(owner, target)
    return target, raw, owner


def _plain(value):
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _variant(repo_root: Path, key: str):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*", key):
        raise ClientStateError("client must be a canonical family/variant key", code="invalid_client")
    family, variant = key.split("/", 1)
    try:
        registry = load_client_registry(repo_root)
        row = registry.variant(family, variant)
        snapshot = {
            "key": row.key,
            "registry_schema_version": registry.schema_version,
            "variant": _plain(row.data),
        }
        digest = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return registry, row, digest
    except (KeyError, ClientRegistryError) as exc:
        raise ClientStateError("unknown or invalid client variant", code="invalid_client") from exc


def resolve_state_location(
    repo_root: Path,
    client: str,
    *,
    cwd: Path,
    home: Path,
    scope: str = "auto",
) -> StateLocation:
    if scope not in {"auto", "repo", "global"}:
        raise ClientStateError(f"unsupported state scope: {scope}")
    repo_root = repo_root.resolve(strict=True)
    cwd = cwd.expanduser().resolve(strict=True)
    home = home.expanduser().resolve()
    registry, variant, variant_digest = _variant(repo_root, client)
    git = None if scope == "global" else probe_git_context(cwd)
    selected = "repo" if git is not None else "global"
    if scope == "repo" and git is None:
        raise ClientStateError("repo scope requested outside a Git worktree")
    if scope == "global":
        selected = "global"

    state = variant.data["state"][selected]
    if state["status"] != "supported" or not state["path"]:
        raise ClientStateError(f"{client} has no supported {selected} state root")
    raw = str(state["path"])
    if selected == "repo":
        assert git is not None
        root = Path(os.path.abspath(git.root / raw))
        _assert_no_symlink(git.root, root)
        display = root.relative_to(git.root).as_posix()
        owner_root = git.root
    else:
        root, display, owner_root = _global_path(raw, home=home)
        git = None
    return StateLocation(
        client=client,
        scope=selected,
        requested_scope=scope,
        repo_root=repo_root,
        cwd=cwd,
        home=home,
        owner_root=owner_root,
        owner_identity=_identity(owner_root),
        root=root,
        root_identity=_identity(root),
        state_path=display,
        git=git,
        registry_schema_version=registry.schema_version,
        variant_digest=variant_digest,
    )


def refresh_state_location(location: StateLocation, *, allow_created_roots: bool = False) -> StateLocation:
    current = resolve_state_location(
        location.repo_root,
        location.client,
        cwd=location.cwd,
        home=location.home,
        scope=location.requested_scope,
    )
    stable = (
        "client", "scope", "owner_root", "root", "state_path",
        "registry_schema_version", "variant_digest",
    )
    identities_match = (
        current.owner_identity == location.owner_identity
        and current.root_identity == location.root_identity
    )
    if allow_created_roots:
        identities_match = (
            location.owner_identity in {None, current.owner_identity}
            and location.root_identity in {None, current.root_identity}
        )
    if (
        any(getattr(current, field) != getattr(location, field) for field in stable)
        or current.git != location.git
        or not identities_match
    ):
        raise ClientStateError("client state binding is stale", code="stale_state_binding")
    return current
