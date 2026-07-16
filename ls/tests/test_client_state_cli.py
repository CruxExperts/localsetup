from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from ls.core.cli import main
from ls.core import cli_client_state_commands
from ls.core.client_state import ClientStateError, artifacts, git_exclude, locator


ROOT = Path(__file__).resolve().parents[2]
FD_ROOT = Path("/proc/self/fd") if Path("/proc/self/fd").is_dir() else Path("/dev/fd")


@pytest.fixture(autouse=True)
def deterministic_safe_creation_umask():
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def repository(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@localsetup.invalid"], check=True)
    (path / "tracked").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "tracked"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
    return path


def invoke(capsys, *args: str) -> tuple[int, dict]:
    result = main(["--source-root", str(ROOT), *args])
    output = capsys.readouterr()
    return result, json.loads(output.out) if output.out else {"stderr": output.err}


def allocation_args() -> list[str]:
    return [
        "--purpose", "handoff", "--extension", "md", "--kind", "restart-artifact",
        "--schema", "restart-v1", "--producer", "controller",
    ]


def descriptor_count() -> int:
    return len(list(FD_ROOT.iterdir()))


STATE_COMPONENT_CASES = (
    ("repo-intermediate", "repo", "codex/codex-cli"),
    ("repo-final", "repo", "codex/codex-cli"),
    ("global-owner", "global", "codex/codex-cli"),
    ("global-intermediate", "global", "opencode/opencode-cli"),
    ("global-final", "global", "opencode/opencode-cli"),
)


def stat_with_uid(result: os.stat_result, uid: int) -> os.stat_result:
    fields = list(result)
    fields[4] = uid
    return os.stat_result(fields)


def stat_with_dev(result: os.stat_result, device: int) -> os.stat_result:
    fields = list(result)
    fields[2] = device
    return os.stat_result(fields)


def test_state_path_is_read_only_until_apply(tmp_path: Path, capsys) -> None:
    repo = repository(tmp_path / "repo")
    code, payload = invoke(
        capsys, "state", "path", "--client", "codex/codex-cli", "--directory", str(repo)
    )
    assert code == 0 and payload["exclude"]["action"] == "append"
    exclude = Path(subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"],
        check=True, capture_output=True, text=True,
    ).stdout.strip())
    assert "/.codex/state/" not in exclude.read_text(encoding="utf-8")

    code, payload = invoke(
        capsys, "state", "path", "--client", "codex/codex-cli", "--directory", str(repo), "--apply-exclude"
    )
    assert code == 0 and payload["exclude"]["action"] == "applied"


def test_state_allocate_and_verify_cli(tmp_path: Path, capsys) -> None:
    repo = repository(tmp_path / "repo")
    content = tmp_path / "payload.md"
    content.write_text("restart\n", encoding="utf-8")
    code, allocated = invoke(
        capsys,
        "state", "allocate", "--client", "codex/codex-cli", "--directory", str(repo),
        "--agent", "controller", "--purpose", "restart-handoff", "--extension", "md",
        "--kind", "restart-artifact", "--schema", "restart-v1", "--producer", "controller",
        "--consumer", "codex", "--content-file", str(content),
    )
    assert code == 0 and allocated["ok"]
    assert str(repo) not in json.dumps(allocated)

    code, verified = invoke(
        capsys,
        "state", "verify", "--client", "codex/codex-cli", "--directory", str(repo),
        "--artifact", allocated["artifact"],
    )
    assert code == 0 and verified["ok"]

    (repo / ".codex" / "state" / allocated["artifact"]).write_text("changed\n", encoding="utf-8")
    code, verified = invoke(
        capsys,
        "state", "verify", "--client", "codex/codex-cli", "--directory", str(repo),
        "--artifact", allocated["artifact"],
    )
    assert code == 1 and not verified["ok"]


def test_state_cli_broken_gitdir_is_private_and_never_allocates_global_state(
    tmp_path: Path, capsys
) -> None:
    cwd = tmp_path / "private-broken-repo"
    cwd.mkdir()
    (cwd / ".git").write_text("gitdir: ../private-missing-gitdir\n", encoding="utf-8")
    home = tmp_path / "private-home"
    code, payload = invoke(
        capsys,
        "--home", str(home), "state", "allocate", "--client", "codex/codex-cli",
        "--directory", str(cwd), *allocation_args(),
    )

    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2 and payload["error"]["code"] == "git_probe_failed"
    assert "Traceback" not in encoded and str(cwd) not in encoded and str(home) not in encoded
    assert not (home / ".codex" / "state").exists()


def test_state_cli_git_marker_discovery_stops_at_mount_boundary(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    foreign_parent = tmp_path / "private-foreign-filesystem"
    foreign_parent.mkdir()
    (foreign_parent / ".git").write_text(
        "gitdir: ../private-missing-gitdir\n", encoding="utf-8"
    )
    cwd = foreign_parent / "mount-root" / "nested"
    cwd.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    original = Path.stat
    foreign_device = foreign_parent.stat().st_dev + 1

    def mounted(path: Path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        return stat_with_dev(result, foreign_device) if path == foreign_parent else result

    monkeypatch.setattr(Path, "stat", mounted)
    code, payload = invoke(
        capsys,
        "--home", str(home), "state", "path", "--client", "codex/codex-cli",
        "--directory", str(cwd),
    )

    assert code == 0 and payload["scope"] == "global"
    assert not (home / ".codex" / "state").exists()


def test_state_cli_git_marker_mount_stat_uncertainty_is_private_and_non_mutating(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    uncertain_parent = tmp_path / "private-uncertain-parent"
    cwd = uncertain_parent / "nested"
    cwd.mkdir(parents=True)
    home = tmp_path / "private-home"
    original = Path.stat

    def uncertain(path: Path, *args, **kwargs):
        if path == uncertain_parent:
            raise PermissionError("private mount-boundary detail")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", uncertain)
    code, payload = invoke(
        capsys,
        "--home", str(home), "state", "allocate", "--client", "codex/codex-cli",
        "--directory", str(cwd), *allocation_args(),
    )

    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2 and payload["error"]["code"] == "git_probe_failed"
    assert "Traceback" not in encoded
    assert all(str(path) not in encoded for path in (uncertain_parent, cwd, home))
    assert not (home / ".codex" / "state").exists()


def test_state_cli_existing_root_preflight_precedes_exclude_and_closes_descriptors(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "private-repo")
    state = repo / ".codex" / "state"
    state.mkdir(parents=True)
    exclude = repo / ".git" / "info" / "exclude"
    before = exclude.read_bytes()
    original = artifacts._open_location_directory

    def deny_readiness(location, *, create: bool, **kwargs):
        if not create:
            raise PermissionError("private state-root detail")
        return original(location, create=create, **kwargs)

    monkeypatch.setattr(artifacts, "_open_location_directory", deny_readiness)
    before_fds = descriptor_count()
    code, payload = invoke(
        capsys,
        "state", "allocate", "--client", "codex/codex-cli", "--directory", str(repo),
        *allocation_args(),
    )

    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2 and payload["error"]["code"] == "unsafe_state_path"
    assert "Traceback" not in encoded and str(repo) not in encoded
    assert exclude.read_bytes() == before
    assert list(state.iterdir()) == []
    assert descriptor_count() == before_fds


def test_state_cli_rejects_new_unsafe_pre_owner_intermediate_privately(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    boundary = tmp_path / "private-boundary"
    boundary.mkdir()
    owner = boundary / "appears-later" / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(owner))
    original = artifacts._open_absolute_directory

    def create_intermediate_then_open(path: Path, **kwargs):
        intermediate = boundary / "appears-later"
        intermediate.mkdir()
        intermediate.chmod(0o777)
        return original(path, **kwargs)

    monkeypatch.setattr(artifacts, "_open_absolute_directory", create_intermediate_then_open)
    code, payload = invoke(
        capsys,
        "--home", str(tmp_path / "home"), "state", "allocate",
        "--client", "codex/codex-cli", "--scope", "global",
        "--directory", str(plain), *allocation_args(),
    )

    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2 and payload["error"]["code"] == "unsafe_state_path"
    assert "Traceback" not in encoded and str(boundary) not in encoded
    assert not owner.exists()
    assert list((boundary / "appears-later").iterdir()) == []


def test_state_cli_existing_global_owner_rejects_unsafe_immediate_parent(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    immediate_parent = tmp_path / "private-unsafe-parent"
    immediate_parent.mkdir()
    immediate_parent.chmod(0o777)
    owner = immediate_parent / "codex-home"
    owner.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(owner))
    code, payload = invoke(
        capsys,
        "--home", str(tmp_path / "home"), "state", "allocate",
        "--client", "codex/codex-cli", "--scope", "global",
        "--directory", str(plain), *allocation_args(),
    )

    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2 and payload["error"]["code"] == "unsafe_state_path"
    assert "Traceback" not in encoded and str(immediate_parent) not in encoded
    assert not (owner / "state").exists()


@pytest.mark.parametrize(
    ("agent_args", "expected_agent"),
    [([], "codex-cli"), (["--agent", "worker"], "worker")],
    ids=["omitted", "explicit"],
)
def test_state_allocate_cli_defaults_only_an_omitted_agent(
    tmp_path: Path, capsys, agent_args: list[str], expected_agent: str
) -> None:
    repo = repository(tmp_path / "repo")
    code, allocated = invoke(
        capsys,
        "state", "allocate", "--client", "codex/codex-cli", "--directory", str(repo),
        *allocation_args(), *agent_args,
    )
    assert code == 0 and allocated["ok"]
    assert allocated["artifact"].startswith(f"{expected_agent}-")
    code, verified = invoke(
        capsys,
        "state", "verify", "--client", "codex/codex-cli", "--directory", str(repo),
        "--artifact", allocated["artifact"],
    )
    assert code == 0 and verified["ok"]


def test_state_allocate_cli_rejects_explicit_empty_agent_without_mutation(
    tmp_path: Path, capsys
) -> None:
    repo = repository(tmp_path / "private-repo")
    exclude = repo / ".git" / "info" / "exclude"
    before = exclude.read_bytes()
    code, payload = invoke(
        capsys,
        "state", "allocate", "--client", "codex/codex-cli", "--directory", str(repo),
        *allocation_args(), "--agent", "",
    )
    assert code == 2
    assert payload == {
        "error": {
            "code": "invalid_agent",
            "message": "agent must be lowercase kebab-case and at most 48 characters",
        },
        "ok": False,
    }
    encoded = json.dumps(payload, sort_keys=True)
    assert "Traceback" not in encoded and str(repo) not in encoded
    assert exclude.read_bytes() == before
    assert not (repo / ".codex" / "state").exists()


@pytest.mark.parametrize("action", ["path", "allocate", "verify"])
def test_state_cli_component_collision_is_typed_private_and_non_mutating(
    tmp_path: Path, capsys, action: str
) -> None:
    repo = repository(tmp_path / "private-collision-repo")
    collision = repo / ".codex"
    collision.write_bytes(b"foreign\n")
    exclude = repo / ".git" / "info" / "exclude"
    before = exclude.read_bytes()
    args = ["state", action, "--client", "codex/codex-cli", "--directory", str(repo)]
    if action == "allocate":
        args.extend(allocation_args())
    elif action == "verify":
        args.extend(["--artifact", "codex-cli-20260715T000000000Z-handoff.md"])
    code, payload = invoke(capsys, *args)
    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2
    assert payload == {
        "error": {
            "code": "unsafe_state_path",
            "message": "client state path components must be directories",
        },
        "ok": False,
    }
    assert str(repo) not in encoded and "Traceback" not in encoded
    assert collision.read_bytes() == b"foreign\n"
    assert exclude.read_bytes() == before


@pytest.mark.parametrize("action", ["path", "allocate", "verify"])
@pytest.mark.parametrize("node_kind", ["file", "symlink", "directory"])
@pytest.mark.parametrize(
    ("case", "scope", "client"),
    STATE_COMPONENT_CASES,
    ids=[row[0] for row in STATE_COMPONENT_CASES],
)
def test_state_cli_registered_component_matrix_is_safe_and_deterministic(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    scope: str,
    client: str,
    node_kind: str,
    action: str,
) -> None:
    wrong = repository(tmp_path / "wrong-target")
    wrong_exclude = wrong / ".git" / "info" / "exclude"
    wrong_before = wrong_exclude.read_bytes()
    monkeypatch.chdir(wrong)
    home = tmp_path / "private-home"
    home.mkdir()
    if scope == "repo":
        directory = repository(tmp_path / "private-repo")
        repo_exclude = directory / ".git" / "info" / "exclude"
        exclude_before = repo_exclude.read_bytes()
        owner = directory / ".codex"
        state_root = owner / "state"
        target = owner if case == "repo-intermediate" else state_root
    else:
        directory = tmp_path / "plain"
        directory.mkdir()
        repo_exclude = None
        exclude_before = None
        if case == "global-owner":
            owner = tmp_path / "private-codex-home"
            monkeypatch.setenv("CODEX_HOME", str(owner))
            state_root = owner / "state"
            target = owner
        else:
            owner = home
            intermediate = home / ".config" / "opencode"
            state_root = intermediate / "state"
            target = intermediate if case == "global-intermediate" else state_root

    outside = tmp_path / f"outside-{case}-{node_kind}-{action}"
    if node_kind == "directory":
        state_root.mkdir(parents=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        if node_kind == "file":
            target.write_bytes(b"foreign\n")
        else:
            outside.mkdir()
            target.symlink_to(outside, target_is_directory=True)
    args = [
        "--home", str(home), "state", action, "--client", client,
        "--scope", scope, "--directory", str(directory),
    ]
    if action == "allocate":
        args.extend(allocation_args())
    elif action == "verify":
        args.extend(["--artifact", "controller-20260715T000000000Z-handoff.md"])
    code, payload = invoke(capsys, *args)
    encoded = json.dumps(payload, sort_keys=True)

    assert wrong_exclude.read_bytes() == wrong_before
    assert not (wrong / ".codex" / "state").exists()
    assert not (wrong / ".opencode" / "state").exists()
    assert not (wrong / ".config" / "opencode" / "state").exists()
    if node_kind != "directory":
        assert code == 2 and payload["error"]["code"] == "unsafe_state_path"
        assert "Traceback" not in encoded
        assert all(str(path) not in encoded for path in (directory, home, target, outside))
        if node_kind == "file":
            assert target.read_bytes() == b"foreign\n"
        else:
            assert target.is_symlink() and target.readlink() == outside
            assert list(outside.iterdir()) == []
        assert not state_root.exists() if target != state_root else True
        assert not list(target.parent.glob(".localsetup-*"))
        assert not list(target.parent.glob("*.meta.json"))
        if repo_exclude is not None:
            assert repo_exclude.read_bytes() == exclude_before
        return

    if action == "path":
        assert code == 0 and payload["ok"]
        assert list(state_root.iterdir()) == []
        if repo_exclude is not None:
            assert repo_exclude.read_bytes() == exclude_before
    elif action == "allocate":
        assert code == 0 and payload["ok"]
        assert (state_root / payload["artifact"]).is_file()
        assert (state_root / payload["metadata"]).is_file()
        if repo_exclude is not None:
            assert b"/.codex/state/" in repo_exclude.read_bytes()
    else:
        assert code == 2 and payload["error"]["code"] == "invalid_artifact"
        assert list(state_root.iterdir()) == []
        if repo_exclude is not None:
            assert repo_exclude.read_bytes() == exclude_before


@pytest.mark.parametrize("action", ["path", "allocate", "verify"])
@pytest.mark.parametrize("position", ["owner", "intermediate", "root"])
def test_global_cli_foreign_locator_ownership_is_typed_private_and_non_mutating(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    position: str,
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    home = tmp_path / "private-home"
    if position == "owner":
        owner = tmp_path / "private-codex-home"
        owner.mkdir()
        monkeypatch.setenv("CODEX_HOME", str(owner))
        client = "codex/codex-cli"
        state = owner / "state"
        target = owner
    else:
        state = home / ".config" / "opencode" / "state"
        state.mkdir(parents=True)
        client = "opencode/opencode-cli"
        target = state.parent if position == "intermediate" else state
    original = Path.stat

    def foreign(path: Path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        return stat_with_uid(result, os.geteuid() + 1) if path == target else result

    monkeypatch.setattr(Path, "stat", foreign)
    args = [
        "--home", str(home), "state", action, "--client", client,
        "--scope", "global", "--directory", str(plain),
    ]
    if action == "allocate":
        args.extend(allocation_args())
    elif action == "verify":
        args.extend(["--artifact", "controller-20260715T000000000Z-handoff.md"])
    code, payload = invoke(capsys, *args)
    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2 and payload["error"]["code"] == "unsafe_state_path"
    assert str(target) not in encoded and "Traceback" not in encoded
    assert not state.exists() if position == "owner" else list(state.iterdir()) == []


@pytest.mark.parametrize("position", ["owner", "intermediate", "root"])
def test_global_cli_allocator_rechecks_descriptor_ownership(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    position: str,
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    home = tmp_path / "home"
    state = home / ".config" / "opencode" / "state"
    state.mkdir(parents=True)
    targets = {"owner": home, "intermediate": state.parent, "root": state}
    target_details = targets[position].stat()
    target_identity = (target_details.st_dev, target_details.st_ino)
    real_fstat = os.fstat

    def foreign_descriptor(fd: int):
        result = real_fstat(fd)
        if (result.st_dev, result.st_ino) == target_identity:
            return stat_with_uid(result, os.geteuid() + 1)
        return result

    monkeypatch.setattr(artifacts.os, "fstat", foreign_descriptor)
    code, payload = invoke(
        capsys,
        "--home", str(home), "state", "allocate", "--client", "opencode/opencode-cli",
        "--scope", "global", "--directory", str(plain), *allocation_args(),
    )
    assert code == 2 and payload["error"]["code"] == "unsafe_state_path"
    assert list(state.iterdir()) == []


@pytest.mark.parametrize("action", ["allocate", "verify"])
def test_global_cli_pre_owner_descriptor_uid_change_is_private_and_non_mutating(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    repo = repository(tmp_path / "private-repo")
    exclude = repo / ".git" / "info" / "exclude"
    before = exclude.read_bytes()
    container = tmp_path / "private-container"
    container.mkdir()
    owner = container / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(owner))
    target_details = container.stat()
    target_identity = (target_details.st_dev, target_details.st_ino)
    real_fstat = os.fstat

    def foreign_descriptor(fd: int):
        result = real_fstat(fd)
        if (result.st_dev, result.st_ino) == target_identity:
            return stat_with_uid(result, os.geteuid() + 1)
        return result

    monkeypatch.setattr(artifacts.os, "fstat", foreign_descriptor)
    args = [
        "--home", str(tmp_path / "home"), "state", action,
        "--client", "codex/codex-cli", "--scope", "global",
        "--directory", str(repo),
    ]
    if action == "allocate":
        args.extend(allocation_args())
    else:
        args.extend(["--artifact", "codex-cli-20260715T120000000Z-w18-probe.md"])
    code, payload = invoke(capsys, *args)
    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2 and payload["error"]["code"] == "unsafe_state_path"
    assert "Traceback" not in encoded and str(container) not in encoded
    assert exclude.read_bytes() == before
    assert not owner.exists()
    assert list(container.iterdir()) == []


@pytest.mark.parametrize("control", ["root-pre-owner", "system-ancestor", "repo-root"])
def test_cli_ownership_controls_preserve_system_and_repo_behavior(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    control: str,
) -> None:
    original = Path.stat
    home = tmp_path / "home"
    if control == "repo-root":
        directory = repository(tmp_path / "repo")
        target = directory
        replacement_uid = os.geteuid() + 1
        args = ["state", "path", "--client", "codex/codex-cli", "--directory", str(directory)]
    else:
        directory = tmp_path / "plain"
        directory.mkdir()
        container = tmp_path / "container"
        container.mkdir()
        owner = container / "codex"
        monkeypatch.setenv("CODEX_HOME", str(owner))
        if control == "root-pre-owner":
            target = container
            replacement_uid = 0
        else:
            owner.mkdir()
            target = tmp_path.parent
            replacement_uid = os.geteuid() + 1
        args = [
            "--home", str(home), "state", "path", "--client", "codex/codex-cli",
            "--scope", "global", "--directory", str(directory),
        ]

    def controlled(path: Path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        return stat_with_uid(result, replacement_uid) if path == target else result

    monkeypatch.setattr(Path, "stat", controlled)
    code, payload = invoke(capsys, *args)
    assert code == 0 and payload["ok"]


@pytest.mark.parametrize("action", ["path", "allocate", "verify"])
@pytest.mark.parametrize("position", ["owner", "intermediate", "root"])
@pytest.mark.parametrize("mode", [0o770, 0o777, 0o1777, 0o2770])
def test_global_cli_rejects_unsafe_managed_directory_modes_without_mutation(
    tmp_path: Path, capsys, action: str, position: str, mode: int
) -> None:
    plain = tmp_path / "private-plain"
    plain.mkdir()
    home = tmp_path / "private-home"
    state = home / ".config" / "opencode" / "state"
    state.mkdir(parents=True)
    targets = {"owner": home, "intermediate": state.parent, "root": state}
    artifact: str | None = None
    if action == "verify":
        code, allocated = invoke(
            capsys,
            "--home", str(home), "state", "allocate", "--client", "opencode/opencode-cli",
            "--scope", "global", "--directory", str(plain), *allocation_args(),
        )
        assert code == 0
        artifact = allocated["artifact"]
    before = {path.name: path.read_bytes() for path in state.iterdir() if path.is_file()}
    targets[position].chmod(mode)
    args = [
        "--home", str(home), "state", action, "--client", "opencode/opencode-cli",
        "--scope", "global", "--directory", str(plain),
    ]
    if action == "allocate":
        args.extend(allocation_args())
    elif action == "verify":
        assert artifact is not None
        args.extend(["--artifact", artifact])
    code, payload = invoke(capsys, *args)
    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2 and payload["error"]["code"] == "unsafe_state_path"
    assert "Traceback" not in encoded and str(home) not in encoded
    assert {path.name: path.read_bytes() for path in state.iterdir() if path.is_file()} == before


@pytest.mark.parametrize("suffix", [" ", "\t"])
def test_state_cli_preserves_trailing_whitespace_git_root_and_never_mutates_sibling(
    tmp_path: Path, capsys, suffix: str
) -> None:
    actual = repository(tmp_path / f"repo{suffix}")
    sibling = repository(tmp_path / "repo")
    code, path_payload = invoke(
        capsys, "state", "path", "--client", "codex/codex-cli", "--directory", str(actual)
    )
    assert code == 0 and path_payload["repository"]["root"] == "."
    code, allocated = invoke(
        capsys, "state", "allocate", "--client", "codex/codex-cli",
        "--directory", str(actual), *allocation_args(),
    )
    assert code == 0 and allocated["ok"]
    code, verified = invoke(
        capsys, "state", "verify", "--client", "codex/codex-cli",
        "--directory", str(actual), "--artifact", allocated["artifact"],
    )
    assert code == 0 and verified["ok"]
    assert (actual / ".codex" / "state" / allocated["artifact"]).is_file()
    assert not (sibling / ".codex" / "state").exists()
    assert b"/.codex/state/" not in (sibling / ".git" / "info" / "exclude").read_bytes()


def test_state_cli_rejects_carriage_return_git_root_without_redirect(
    tmp_path: Path, capsys
) -> None:
    actual = repository(tmp_path / "repo\r")
    sibling = repository(tmp_path / "repo")
    code, payload = invoke(
        capsys, "state", "allocate", "--client", "codex/codex-cli",
        "--directory", str(actual), *allocation_args(),
    )
    assert code == 2 and payload["error"]["code"] == "git_probe_failed"
    assert not (actual / ".codex" / "state").exists()
    assert not (sibling / ".codex" / "state").exists()


def test_state_cli_preserves_undecodable_git_root_without_replacement_redirect(
    tmp_path: Path, capsys
) -> None:
    actual = repository(tmp_path / os.fsdecode(b"repo-\xff"))
    sibling = repository(tmp_path / "repo-\ufffd")
    code, allocated = invoke(
        capsys, "state", "allocate", "--client", "codex/codex-cli",
        "--directory", str(actual), *allocation_args(),
    )
    assert code == 0 and allocated["ok"]
    code, verified = invoke(
        capsys, "state", "verify", "--client", "codex/codex-cli",
        "--directory", str(actual), "--artifact", allocated["artifact"],
    )
    assert code == 0 and verified["ok"]
    assert (actual / ".codex" / "state" / allocated["artifact"]).is_file()
    assert not (sibling / ".codex" / "state").exists()


def test_top_level_target_drives_path_allocate_and_verify_without_wrong_target_mutation(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = repository(tmp_path / "target")
    wrong = repository(tmp_path / "wrong")
    monkeypatch.chdir(wrong)
    prefix = ("--target-directory", str(target), "state")

    code, path_payload = invoke(capsys, *prefix, "path", "--client", "codex/codex-cli")
    assert code == 0 and path_payload["scope"] == "repo"

    code, allocated = invoke(
        capsys, *prefix, "allocate", "--client", "codex/codex-cli", *allocation_args()
    )
    assert code == 0 and allocated["ok"]
    assert (target / ".codex" / "state" / allocated["artifact"]).is_file()
    assert not (wrong / ".codex" / "state").exists()

    code, verified = invoke(
        capsys, *prefix, "verify", "--client", "codex/codex-cli",
        "--artifact", allocated["artifact"],
    )
    assert code == 0 and verified["ok"]


def test_explicit_state_directory_precedes_top_level_target_including_dot(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = repository(tmp_path / "explicit")
    target = repository(tmp_path / "target")
    monkeypatch.chdir(explicit)
    code, payload = invoke(
        capsys, "--target-directory", str(target), "state", "path",
        "--client", "codex/codex-cli", "--directory", ".", "--apply-exclude",
    )
    assert code == 0 and payload["scope"] == "repo"
    assert payload["exclude"]["action"] == "applied"
    explicit_exclude = explicit / ".git" / "info" / "exclude"
    target_exclude = target / ".git" / "info" / "exclude"
    assert "/.codex/state/" in explicit_exclude.read_text(encoding="utf-8")
    assert "/.codex/state/" not in target_exclude.read_text(encoding="utf-8")


@pytest.mark.parametrize("action", ["path", "allocate"])
def test_cli_rejects_same_path_whole_repo_replacement_before_exclude_or_state_mutation(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    repo = repository(tmp_path / "private-repo")
    original_apply = cli_client_state_commands.apply_git_exclude
    replacement_exclude: Path | None = None

    def replace_repo_then_apply(plan):
        nonlocal replacement_exclude
        repo.rename(tmp_path / "private-repo-prior")
        replacement = repository(repo)
        replacement_exclude = replacement / ".git" / "info" / "exclude"
        return original_apply(plan)

    monkeypatch.setattr(cli_client_state_commands, "apply_git_exclude", replace_repo_then_apply)
    args = [
        "state", action, "--client", "codex/codex-cli", "--directory", str(repo),
    ]
    if action == "path":
        args.append("--apply-exclude")
    else:
        args.extend(allocation_args())
    code, payload = invoke(capsys, *args)
    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2 and payload["error"]["code"] == "stale_state_binding"
    assert "Traceback" not in encoded and str(repo) not in encoded
    assert replacement_exclude is not None
    assert b"/.codex/state/" not in replacement_exclude.read_bytes()
    assert not replacement_exclude.with_name("exclude.localsetup.lock").exists()
    assert not (repo / ".codex" / "state").exists()


@pytest.mark.parametrize("action", ["path", "allocate"])
@pytest.mark.parametrize("scenario", ["probe-error", "already-ignored", "ineffective"])
def test_cli_planned_absent_failures_and_concurrent_ignore_restore_absence_privately(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, action: str, scenario: str
) -> None:
    repo = repository(tmp_path / "private-repo")
    exclude = repo / ".git" / "info" / "exclude"
    exclude.unlink()
    calls = 0

    real_effective_ignore = git_exclude._effective_ignore

    def controlled_probe(root: Path, entry: str) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2 and scenario == "probe-error":
            raise ClientStateError("ignore probe failed", code="git_ignore_probe_failed")
        if calls == 2 and scenario == "already-ignored":
            (repo / ".gitignore").write_text("/.codex/state/\n", encoding="utf-8")
            return real_effective_ignore(root, entry)
        return False

    monkeypatch.setattr(git_exclude, "_effective_ignore", controlled_probe)
    if scenario != "ineffective":
        monkeypatch.setattr(
            git_exclude,
            "_create_mutable_regular_exclusive",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("planned-absent probe must precede creation")
            ),
        )
    args = ["state", action, "--client", "codex/codex-cli", "--directory", str(repo)]
    if action == "path":
        args.append("--apply-exclude")
    else:
        args.extend(allocation_args())
    code, payload = invoke(capsys, *args)
    encoded = json.dumps(payload, sort_keys=True)
    if scenario == "already-ignored":
        assert code == 0 and payload["exclude"]["action"] == "already-ignored"
    else:
        expected = (
            "git_ignore_probe_failed"
            if scenario == "probe-error"
            else "exclude_commit_ambiguous"
        )
        assert code == 2 and payload["error"]["code"] == expected
    assert "Traceback" not in encoded and str(repo) not in encoded
    if scenario == "ineffective":
        assert exclude.read_bytes() == b"/.codex/state/\n"
    else:
        assert not exclude.exists()
    assert (repo / ".codex" / "state").exists() == (
        scenario == "already-ignored" and action == "allocate"
    )


@pytest.mark.parametrize("action", ["path", "allocate"])
@pytest.mark.parametrize("phase", ["postcreate-prewrite", "postwrite"])
def test_cli_created_foreign_exclude_bytes_are_preserved_with_private_ambiguity(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    phase: str,
) -> None:
    repo = repository(tmp_path / "private-repo")
    exclude = repo / ".git" / "info" / "exclude"
    exclude.unlink()
    foreign = b"/foreign-before-local/\n"
    if phase == "postcreate-prewrite":
        real_read = git_exclude._read_fd
        injected = False

        def inject_foreign_then_fail_read(fd: int) -> bytes:
            nonlocal injected
            exclude_details = exclude.stat()
            fd_details = os.fstat(fd)
            if (
                (fd_details.st_dev, fd_details.st_ino)
                == (exclude_details.st_dev, exclude_details.st_ino)
                and not injected
            ):
                injected = True
                with exclude.open("ab") as handle:
                    handle.write(foreign)
                raise OSError("injected post-creation read failure")
            return real_read(fd)

        monkeypatch.setattr(git_exclude, "_read_fd", inject_foreign_then_fail_read)
        monkeypatch.setattr(git_exclude, "_effective_ignore", lambda *_args: False)
    else:
        probes = 0

        def controlled_probe(_root: Path, _entry: str) -> bool:
            nonlocal probes
            probes += 1
            if probes == 3:
                with exclude.open("ab") as handle:
                    handle.write(foreign)
            return False

        monkeypatch.setattr(git_exclude, "_effective_ignore", controlled_probe)
    args = ["state", action, "--client", "codex/codex-cli", "--directory", str(repo)]
    if action == "path":
        args.append("--apply-exclude")
    else:
        args.extend(allocation_args())
    baseline = descriptor_count()
    code, payload = invoke(capsys, *args)
    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2 and payload["error"]["code"] == "exclude_commit_ambiguous"
    assert "Traceback" not in encoded and str(repo) not in encoded
    expected = foreign if phase == "postcreate-prewrite" else b"/.codex/state/\n" + foreign
    assert exclude.read_bytes() == expected
    assert descriptor_count() == baseline
    assert not (repo / ".codex" / "state").exists()


@pytest.mark.parametrize("action", ["path", "allocate"])
@pytest.mark.parametrize("scenario", ["plan-existing", "apply-existing", "apply-created"])
def test_cli_final_invalid_utf8_is_private_and_creates_no_artifact_state(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    scenario: str,
) -> None:
    repo = repository(tmp_path / "private-repo")
    exclude = repo / ".git" / "info" / "exclude"
    if scenario == "apply-created":
        exclude.unlink()
    before = exclude.read_bytes() if exclude.exists() else b""
    real_effective_ignore = git_exclude._effective_ignore
    probes = 0

    def inject_after_real_probe(root: Path, entry: str) -> bool:
        nonlocal probes
        probes += 1
        result = real_effective_ignore(root, entry)
        inject_now = scenario == "plan-existing" and probes == 1
        inject_now = inject_now or scenario == "apply-existing" and probes == 2
        inject_now = inject_now or scenario == "apply-created" and probes == 3
        if inject_now:
            with exclude.open("ab") as handle:
                handle.write(b"\xff" if scenario == "plan-existing" else b"\xff\n")
        return result

    monkeypatch.setattr(git_exclude, "_effective_ignore", inject_after_real_probe)
    args = ["state", action, "--client", "codex/codex-cli", "--directory", str(repo)]
    if action == "path":
        args.append("--apply-exclude")
    else:
        args.extend(allocation_args())
    baseline = descriptor_count()
    code, payload = invoke(capsys, *args)
    encoded = json.dumps(payload, sort_keys=True)
    expected = "unsafe_exclude" if scenario == "plan-existing" else "exclude_commit_ambiguous"
    assert code == 2 and payload["error"]["code"] == expected
    assert "Traceback" not in encoded and str(repo) not in encoded
    suffix = {
        "plan-existing": b"\xff",
        "apply-existing": b"\xff\n/.codex/state/\n",
        "apply-created": b"/.codex/state/\n\xff\n",
    }[scenario]
    assert exclude.read_bytes() == before + suffix
    assert descriptor_count() == baseline
    assert not (repo / ".codex" / "state").exists()


@pytest.mark.parametrize("action", ["path", "allocate"])
@pytest.mark.parametrize("planned_present", [False, True])
def test_cli_lost_lock_postwrite_preserves_current_exclude_privately(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    planned_present: bool,
) -> None:
    repo = repository(tmp_path / "private-repo")
    exclude = repo / ".git" / "info" / "exclude"
    if not planned_present:
        exclude.unlink()
    before = exclude.read_bytes() if planned_present else b""
    lock = exclude.with_name("exclude.localsetup.lock")
    owned = b"/.codex/state/\n"
    contender = b"/contender/\n"
    probes = 0
    injected = False

    def replace_lock_and_append_during_postwrite_probe(_root: Path, _entry: str) -> bool:
        nonlocal probes
        nonlocal injected
        probes += 1
        if probes == 3 and not injected:
            injected = True
            replacement = tmp_path / "replacement-lock"
            replacement.write_bytes(b"replacement\n")
            os.replace(replacement, lock)
            with exclude.open("ab") as handle:
                handle.write(contender)
        return False

    monkeypatch.setattr(
        git_exclude, "_effective_ignore", replace_lock_and_append_during_postwrite_probe
    )
    args = ["state", action, "--client", "codex/codex-cli", "--directory", str(repo)]
    if action == "path":
        args.append("--apply-exclude")
    else:
        args.extend(allocation_args())
    baseline = descriptor_count()
    code, payload = invoke(capsys, *args)
    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2 and payload["error"]["code"] == "exclude_commit_ambiguous"
    assert "Traceback" not in encoded and str(repo) not in encoded
    assert injected and exclude.read_bytes() == before + owned + contender
    assert lock.read_bytes() == b"replacement\n"
    assert descriptor_count() == baseline
    assert not (repo / ".codex" / "state").exists()


@pytest.mark.parametrize("action", ["path", "allocate"])
@pytest.mark.parametrize("planned_present", [False, True])
def test_cli_postwrite_failure_never_uses_destructive_exclude_recovery(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    planned_present: bool,
) -> None:
    repo = repository(tmp_path / "private-repo")
    exclude = repo / ".git" / "info" / "exclude"
    if not planned_present:
        exclude.unlink()
    before = exclude.read_bytes() if planned_present else b""

    def destructive_recovery_forbidden(*_args, **_kwargs):
        raise AssertionError("destructive Git exclude recovery is forbidden")

    monkeypatch.setattr(git_exclude.os, "ftruncate", destructive_recovery_forbidden)
    monkeypatch.setattr(git_exclude.os, "unlink", destructive_recovery_forbidden)
    monkeypatch.setattr(git_exclude, "_effective_ignore", lambda *_args: False)
    args = ["state", action, "--client", "codex/codex-cli", "--directory", str(repo)]
    if action == "path":
        args.append("--apply-exclude")
    else:
        args.extend(allocation_args())
    baseline = descriptor_count()
    code, payload = invoke(capsys, *args)
    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2 and payload["error"]["code"] == "exclude_commit_ambiguous"
    assert "Traceback" not in encoded and str(repo) not in encoded
    assert exclude.read_bytes() == before + b"/.codex/state/\n"
    assert descriptor_count() == baseline
    assert not (repo / ".codex" / "state").exists()


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_codex_home_cli_fails_without_mutation(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    monkeypatch.setenv("CODEX_HOME", value)
    code, payload = invoke(
        capsys, "state", "allocate", "--client", "codex/codex-cli",
        "--scope", "global", "--directory", str(plain), *allocation_args(),
    )
    assert code == 2
    assert payload == {
        "error": {"code": "invalid_environment", "message": "CODEX_HOME must be a non-empty absolute path"},
        "ok": False,
    }
    assert not (plain / "state").exists()


def test_fifo_content_is_rejected_promptly_without_mutation(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    fifo = tmp_path / "content.fifo"
    fifo.parent.mkdir(exist_ok=True)
    fifo.unlink(missing_ok=True)
    os.mkfifo(fifo)
    command = [
        sys.executable, str(ROOT / "ls" / "tools" / "localsetup.py"),
        "--source-root", str(ROOT), "state", "allocate", "--client", "codex/codex-cli",
        "--directory", str(repo), *allocation_args(), "--content-file", str(fifo),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=3, check=False)
    payload = json.loads(completed.stdout)
    assert completed.returncode == 2 and payload["error"]["code"] == "invalid_content"
    assert not (repo / ".codex" / "state").exists()
    assert "/.codex/state/" not in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")


@pytest.mark.parametrize("field", ["predecessor", "checkpoint"])
def test_oversized_relative_metadata_cli_rejects_without_mutation(
    tmp_path: Path, capsys, field: str
) -> None:
    repo = repository(tmp_path / "repo")
    code, payload = invoke(
        capsys, "state", "allocate", "--client", "codex/codex-cli",
        "--directory", str(repo), *allocation_args(), f"--{field}", "a" * 513,
    )
    assert code == 2 and payload["error"]["code"] == f"invalid_{field}"
    assert not (repo / ".codex" / "state").exists()
    assert "/.codex/state/" not in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")


def test_oversized_metadata_cli_rejects_without_mutation(
    tmp_path: Path, capsys
) -> None:
    repo = repository(tmp_path / "repo")
    args = [
        "state", "allocate", "--client", "codex/codex-cli", "--directory", str(repo),
        *allocation_args(),
    ]
    for index in reversed(range(18000)):
        args.extend(["--consumer", f"c{index:05d}-" + ("a" * 55)])
    code, payload = invoke(capsys, *args)
    assert code == 2 and payload["error"]["code"] == "invalid_metadata"
    assert not (repo / ".codex" / "state").exists()
    assert "/.codex/state/" not in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")


def test_explicit_global_scope_ignores_missing_directory_for_path_allocate_verify(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("CODEX_HOME", raising=False)
    prefix = (
        "--home", str(home), "state", "path", "--client", "codex/codex-cli",
        "--scope", "global", "--directory", str(missing),
    )
    code, payload = invoke(capsys, *prefix)
    assert code == 0 and payload["scope"] == "global"
    code, allocated = invoke(
        capsys, "--home", str(home), "state", "allocate", "--client", "codex/codex-cli", "--scope", "global",
        "--directory", str(missing), *allocation_args(),
    )
    assert code == 0 and allocated["ok"]
    code, verified = invoke(
        capsys, "--home", str(home), "state", "verify", "--client", "codex/codex-cli", "--scope", "global",
        "--directory", str(missing), "--artifact", allocated["artifact"],
    )
    assert code == 0 and verified["ok"]


@pytest.mark.parametrize("action", ["path", "allocate", "verify"])
@pytest.mark.parametrize("target_kind", ["missing", "file", "permission"])
def test_invalid_target_has_stable_sanitized_json_and_no_mutation(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, action: str, target_kind: str
) -> None:
    target = tmp_path / "private-invalid-target"
    if target_kind == "file":
        target.write_text("not a directory\n", encoding="utf-8")
    elif target_kind == "permission":
        original_resolve = Path.resolve

        def deny_resolve(path: Path, *args, **kwargs):
            if path == target:
                raise PermissionError("private permission detail")
            return original_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", deny_resolve)
    args = ["state", action, "--client", "codex/codex-cli", "--directory", str(target)]
    if action == "allocate":
        args.extend(allocation_args())
    elif action == "verify":
        args.extend(["--artifact", "codex-20260715T000000000Z-handoff.md"])
    code, payload = invoke(capsys, *args)
    assert code == 2
    assert payload == {
        "error": {"code": "invalid_directory", "message": "state probe directory is unavailable"},
        "ok": False,
    }
    assert str(target) not in json.dumps(payload)
    assert not (tmp_path / ".codex" / "state").exists()


def test_deleted_default_cwd_has_stable_sanitized_json_and_no_mutation(tmp_path: Path) -> None:
    deleted = tmp_path / "private-deleted-cwd"
    deleted.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    script = (
        "import os,sys; "
        "dead,tool,root,home=sys.argv[1:]; "
        "os.chdir(dead); os.rmdir(dead); "
        "os.execv(sys.executable,[sys.executable,tool,'--source-root',root,'--home',home,"
        "'state','path','--client','codex/codex-cli'])"
    )
    completed = subprocess.run(
        [
            sys.executable, "-c", script, str(deleted),
            str(ROOT / "ls" / "tools" / "localsetup.py"), str(ROOT), str(home),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert payload == {
        "error": {"code": "invalid_directory", "message": "state probe directory is unavailable"},
        "ok": False,
    }
    combined = completed.stdout + completed.stderr
    assert str(deleted) not in combined and "Traceback" not in combined
    assert not (home / ".codex" / "state").exists()


def test_state_cli_rejects_unknown_client_without_traceback(tmp_path: Path, capsys) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    code, payload = invoke(
        capsys, "state", "path", "--client", "unknown/unknown-cli", "--directory", str(plain)
    )
    assert code == 2
    assert payload == {
        "error": {"code": "invalid_client", "message": "unknown or invalid client variant"},
        "ok": False,
    }


@pytest.mark.parametrize(
    "replacement",
    [
        ("--agent", "Bad Agent"),
        ("--purpose", "../private"),
        ("--extension", "md.exe"),
        ("--kind", "Bad Kind"),
        ("--schema", "Bad Schema"),
        ("--producer", "Bad Producer"),
        ("--predecessor", "C:/private"),
        ("--checkpoint", "..\\private"),
        ("--consumer", "Bad Consumer"),
        ("--content-file", "/private/missing-payload"),
    ],
)
def test_allocate_prevalidation_never_mutates_exclude_or_state(
    tmp_path: Path, capsys, replacement: tuple[str, str]
) -> None:
    repo = repository(tmp_path / "repo")
    exclude = Path(subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"],
        check=True, capture_output=True, text=True,
    ).stdout.strip())
    before = exclude.read_bytes()
    options = {
        "--agent": "controller", "--purpose": "handoff", "--extension": "md",
        "--kind": "restart-artifact", "--schema": "restart-v1", "--producer": "controller",
    }
    options[replacement[0]] = replacement[1]
    args = ["state", "allocate", "--client", "codex/codex-cli", "--directory", str(repo)]
    for key, value in options.items():
        args.extend([key, value])
    code, payload = invoke(capsys, *args)
    assert code == 2 and payload["ok"] is False
    assert exclude.read_bytes() == before
    assert not (repo / ".codex" / "state").exists()


def test_missing_metadata_schema_fails_before_exclude_mutation(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    config = source / "ls" / "config"
    config.mkdir(parents=True)
    shutil.copy2(ROOT / "ls" / "config" / "clients.yaml", config / "clients.yaml")
    shutil.copy2(ROOT / "ls" / "config" / "clients.schema.json", config / "clients.schema.json")
    repo = repository(tmp_path / "repo")
    exclude = Path(subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"],
        check=True, capture_output=True, text=True,
    ).stdout.strip())
    before = exclude.read_bytes()
    code = main([
        "--source-root", str(source), "state", "allocate", "--client", "codex/codex-cli",
        "--directory", str(repo), "--purpose", "handoff", "--extension", "md",
        "--kind", "restart-artifact", "--schema", "restart-v1", "--producer", "controller",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2 and payload["error"]["code"] == "invalid_metadata_schema"
    assert exclude.read_bytes() == before
    assert not (repo / ".codex" / "state").exists()


def test_fifo_metadata_schema_cli_fails_promptly_without_residue(
    tmp_path: Path, capsys
) -> None:
    source = tmp_path / "source"
    config = source / "ls" / "config"
    config.mkdir(parents=True)
    shutil.copy2(ROOT / "ls" / "config" / "clients.yaml", config / "clients.yaml")
    shutil.copy2(ROOT / "ls" / "config" / "clients.schema.json", config / "clients.schema.json")
    os.mkfifo(config / "client-state-artifact.schema.json")
    repo = repository(tmp_path / "repo")
    exclude = repo / ".git" / "info" / "exclude"
    before = exclude.read_bytes()
    started = time.monotonic()
    code = main([
        "--source-root", str(source), "state", "allocate", "--client", "codex/codex-cli",
        "--directory", str(repo), *allocation_args(),
    ])
    elapsed = time.monotonic() - started
    payload = json.loads(capsys.readouterr().out)
    assert code == 2 and payload["error"]["code"] == "invalid_metadata_schema"
    assert elapsed < 1
    assert exclude.read_bytes() == before
    assert not (repo / ".codex" / "state").exists()


def test_cli_sanitizes_injected_private_git_failure(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "private-home" / "secret-repo"
    plain.mkdir(parents=True)
    private = str(plain)
    failure = subprocess.CompletedProcess(["git"], 2, "", f"fatal: credential TOKEN at {private}")
    monkeypatch.setattr(locator, "_git", lambda *_args: failure)
    code, payload = invoke(
        capsys, "state", "path", "--client", "codex/codex-cli", "--directory", str(plain)
    )
    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2
    assert payload == {
        "error": {"code": "git_probe_failed", "message": "ambiguous Git worktree probe failure"},
        "ok": False,
    }
    assert private not in encoded and "TOKEN" not in encoded
