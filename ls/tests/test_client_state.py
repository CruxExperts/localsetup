from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest

from ls.core.client_state import (
    ClientStateError,
    allocate_artifact,
    apply_git_exclude,
    parse_artifact_name,
    plan_git_exclude,
    prepare_artifact_request,
    probe_git_context,
    resolve_state_location,
    verify_artifact,
)
from ls.core.client_state import locator
from ls.core.client_state import artifacts, git_exclude


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "ls" / "config" / "client-state-artifact.schema.json"
ACCEPTED_RELATIVE_PATHS = (
    "foo",
    "foo/bar",
    "deeply/nested/artifact/path",
    "café/文件",
    "folder name/file name.md",
    "a" * 512,
)
REJECTED_RELATIVE_PATHS = (
    ".",
    "../private",
    "folder\\secret",
    "C:/private",
    "//server/share",
    "folder//file",
    "folder/./file",
    "line\nsecret",
    "foo/",
    "a" * 513,
)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def repository(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.name", "LocalSetup Test")
    git(path, "config", "user.email", "test@localsetup.invalid")
    (path / "tracked").write_text("one\n", encoding="utf-8")
    git(path, "add", "tracked")
    git(path, "commit", "-qm", "test fixture")
    return path


def registry_root(path: Path) -> Path:
    config = path / "ls" / "config"
    config.mkdir(parents=True)
    shutil.copy2(ROOT / "ls" / "config" / "clients.yaml", config / "clients.yaml")
    shutil.copy2(ROOT / "ls" / "config" / "clients.schema.json", config / "clients.schema.json")
    return path


def artifact_options(content: object = b"checkpoint\n") -> dict:
    return {
        "content": content,
        "purpose": "w14-boundary",
        "extension": "md",
        "kind": "restart-artifact",
        "schema": "restart-v1",
        "producer": "controller",
    }


def exclude_bytes(repo: Path) -> bytes:
    return (repo / ".git" / "info" / "exclude").read_bytes()


def test_locator_selects_nested_repo_and_registry_root(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    nested = repo / "one" / "two"
    nested.mkdir(parents=True)
    location = resolve_state_location(
        ROOT, "codex/codex-cli", cwd=nested, home=tmp_path / "home"
    )
    assert location.scope == "repo"
    assert location.root == repo / ".codex" / "state"
    assert location.state_path == ".codex/state"
    assert location.git and location.git.root == repo


def test_locator_uses_worktree_git_path(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    worktree = tmp_path / "worktree"
    git(repo, "worktree", "add", "-qb", "fixture-worktree", str(worktree))
    location = resolve_state_location(
        ROOT, "claude-code/claude-code-cli", cwd=worktree, home=tmp_path / "home"
    )
    assert location.root == worktree / ".claude" / "state"
    assert location.git and location.git.exclude_path.name == "exclude"
    assert location.git.exclude_path.is_absolute()


def test_locator_honors_submodule_root(tmp_path: Path) -> None:
    child = repository(tmp_path / "child")
    parent = repository(tmp_path / "parent")
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "-C", str(parent), "submodule", "add", "-q", str(child), "module"],
        check=True,
    )
    location = resolve_state_location(
        ROOT, "codex/codex-cli", cwd=parent / "module", home=tmp_path / "home"
    )
    assert location.git and location.git.root == parent / "module"
    assert location.root == parent / "module" / ".codex" / "state"


@pytest.mark.parametrize("suffix", [" ", "\t"])
@pytest.mark.parametrize("with_stripped_sibling", [False, True])
def test_git_root_trailing_whitespace_is_preserved_end_to_end(
    tmp_path: Path, suffix: str, with_stripped_sibling: bool
) -> None:
    actual = repository(tmp_path / f"repo{suffix}")
    sibling = repository(tmp_path / "repo") if with_stripped_sibling else tmp_path / "repo"
    location = resolve_state_location(
        ROOT, "codex/codex-cli", cwd=actual, home=tmp_path / "home"
    )
    assert location.git and location.git.root == actual
    allocated = allocate_artifact(location, **artifact_options())
    current = resolve_state_location(
        ROOT, "codex/codex-cli", cwd=actual, home=tmp_path / "home"
    )
    assert verify_artifact(current, allocated["artifact"], schema_path=SCHEMA)["ok"]
    assert (actual / ".codex" / "state" / allocated["artifact"]).is_file()
    assert not (sibling / ".codex" / "state").exists()
    if with_stripped_sibling:
        assert b"/.codex/state/" not in exclude_bytes(sibling)


def test_git_root_terminal_carriage_return_is_typed_and_never_redirected(
    tmp_path: Path
) -> None:
    actual = repository(tmp_path / "repo\r")
    sibling = repository(tmp_path / "repo")
    with pytest.raises(ClientStateError) as failure:
        resolve_state_location(ROOT, "codex/codex-cli", cwd=actual, home=tmp_path / "home")
    assert failure.value.code == "git_probe_failed"
    assert not (actual / ".codex" / "state").exists()
    assert not (sibling / ".codex" / "state").exists()
    assert b"/.codex/state/" not in exclude_bytes(sibling)


def test_git_root_undecodable_byte_is_preserved_without_replacement_sibling_redirect(
    tmp_path: Path
) -> None:
    actual = repository(tmp_path / os.fsdecode(b"repo-\xff"))
    sibling = repository(tmp_path / "repo-\ufffd")
    location = resolve_state_location(
        ROOT, "codex/codex-cli", cwd=actual, home=tmp_path / "home"
    )
    assert location.git and os.fsencode(location.git.root) == os.fsencode(actual)
    allocated = allocate_artifact(location, **artifact_options())
    assert (actual / ".codex" / "state" / allocated["artifact"]).is_file()
    assert not (sibling / ".codex" / "state").exists()
    assert b"/.codex/state/" not in exclude_bytes(sibling)


@pytest.mark.parametrize(
    "record",
    [
        b"/tmp/repo",
        b"\n",
        b"relative/repo\n",
        b"/tmp/repo\x00evil\n",
        b"/tmp/one\n/tmp/two\n",
        b"/tmp/repo\r\n",
    ],
)
def test_path_valued_git_records_require_one_clean_lf_delimited_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record: bytes
) -> None:
    result = subprocess.CompletedProcess(["git"], 0, record, b"")
    monkeypatch.setattr(locator, "_git_bytes", lambda *_args: result)
    with pytest.raises(ClientStateError) as failure:
        locator._required_git_path(tmp_path, "rev-parse", "--show-toplevel")
    assert failure.value.code == "git_probe_failed"


def test_relative_git_path_record_maps_per_consumer_without_wrong_target_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    (tmp_path / "relative").mkdir()
    wrong = repository(tmp_path / "relative" / "repo")
    repo_before = exclude_bytes(repo)
    wrong_before = exclude_bytes(wrong)
    relative = subprocess.CompletedProcess(["git"], 0, b"relative/repo\n", b"")
    monkeypatch.setattr(locator, "_git_bytes", lambda *_args: relative)

    with pytest.raises(ClientStateError) as locator_failure:
        probe_git_context(repo)
    assert locator_failure.value.code == "git_probe_failed"
    with pytest.raises(ClientStateError) as exclude_failure:
        git_exclude._resolved_exclude(repo)
    assert exclude_failure.value.code == "git_ignore_probe_failed"
    assert exclude_bytes(repo) == repo_before and exclude_bytes(wrong) == wrong_before
    assert not (repo / ".codex" / "state").exists()
    assert not (wrong / ".codex" / "state").exists()


def test_non_repo_falls_back_to_supported_global_root(tmp_path: Path) -> None:
    cwd = tmp_path / "plain"
    cwd.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    location = resolve_state_location(
        ROOT, "claude-code/claude-code-cli", cwd=cwd, home=home
    )
    assert location.scope == "global"
    assert location.root == home / ".claude" / "state"
    assert location.state_path == "~/.claude/state"
    assert location.git is None


def test_codex_home_override_can_be_outside_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd = tmp_path / "plain"
    cwd.mkdir()
    codex_home = tmp_path / "client-data" / "codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    location = resolve_state_location(
        ROOT, "codex/codex-cli", cwd=cwd, home=tmp_path / "home", scope="global"
    )
    assert location.root == codex_home / "state"
    assert location.owner_root == codex_home
    assert not location.root.exists()


def test_codex_home_unset_uses_home_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cwd = tmp_path / "plain"
    cwd.mkdir()
    home = tmp_path / "home"
    monkeypatch.delenv("CODEX_HOME", raising=False)
    location = resolve_state_location(
        ROOT, "codex/codex-cli", cwd=cwd, home=home, scope="global"
    )
    assert location.root == home / ".codex" / "state"
    assert location.owner_root == home / ".codex"
    assert not location.root.exists()


@pytest.mark.parametrize("surface", ["kwargs", "prepared"])
def test_artifact_content_exact_limit_allocates_and_verifies(
    tmp_path: Path, surface: str
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    options = artifact_options(b"x" * (16 * 1024 * 1024))
    if surface == "prepared":
        allocated = allocate_artifact(location, prepared=prepare_artifact_request(location, **options))
    else:
        allocated = allocate_artifact(location, **options)
    current = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    assert verify_artifact(current, allocated["artifact"], schema_path=SCHEMA)["ok"]


@pytest.mark.parametrize("surface", ["kwargs", "prepared"])
@pytest.mark.parametrize("invalid", ["oversized", "nonbytes"])
def test_artifact_content_preflight_rejects_without_mutation(
    tmp_path: Path, surface: str, invalid: str
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    before = exclude_bytes(repo)
    content: object = b"x" * (16 * 1024 * 1024 + 1) if invalid == "oversized" else bytearray(b"x")
    with pytest.raises(ClientStateError) as failure:
        if surface == "prepared":
            prepared = prepare_artifact_request(location, **artifact_options())
            allocate_artifact(location, prepared=replace(prepared, content=content))
        else:
            allocate_artifact(location, **artifact_options(content))
    assert failure.value.code == "invalid_content"
    assert exclude_bytes(repo) == before
    assert not (repo / ".codex" / "state").exists()


@pytest.mark.parametrize("value", ["", "   ", "relative-client-home"])
def test_codex_home_invalid_values_fail_without_cwd_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    cwd = tmp_path / "plain"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("CODEX_HOME", value)
    with pytest.raises(ClientStateError) as failure:
        resolve_state_location(
            ROOT, "codex/codex-cli", cwd=cwd, home=tmp_path / "home", scope="global"
        )
    assert failure.value.code == "invalid_environment"
    assert not (cwd / "state").exists()


@pytest.mark.parametrize("scope", ["repo", "global"])
@pytest.mark.parametrize("position", ["owner", "root"])
@pytest.mark.parametrize("node_kind", ["file", "symlink"])
def test_state_path_component_collisions_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    position: str,
    node_kind: str,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    if scope == "repo":
        cwd = repository(tmp_path / "repo")
        target = cwd / ".codex" if position == "owner" else cwd / ".codex" / "state"
        if position == "root":
            target.parent.mkdir()
        before = exclude_bytes(cwd)
    else:
        cwd = tmp_path / "plain"
        cwd.mkdir()
        owner = tmp_path / "codex-home"
        monkeypatch.setenv("CODEX_HOME", str(owner))
        target = owner if position == "owner" else owner / "state"
        if position == "root":
            owner.mkdir()
        before = None
    if node_kind == "file":
        target.write_bytes(b"foreign\n")
    else:
        outside = tmp_path / f"outside-{scope}-{position}"
        outside.mkdir()
        target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ClientStateError) as failure:
        resolve_state_location(
            ROOT, "codex/codex-cli", cwd=cwd, home=home, scope=scope
        )
    assert failure.value.code == "unsafe_state_path"
    if before is not None:
        assert exclude_bytes(cwd) == before
    assert target.is_symlink() if node_kind == "symlink" else target.read_bytes() == b"foreign\n"


def test_codex_home_ancestor_symlink_is_rejected_but_normal_external_home_is_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "plain"
    cwd.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("CODEX_HOME", str(linked / "codex"))
    with pytest.raises(ClientStateError) as failure:
        resolve_state_location(
            ROOT, "codex/codex-cli", cwd=cwd, home=tmp_path / "home", scope="global"
        )
    assert failure.value.code == "unsafe_state_path"
    assert not (outside / "codex").exists()

    external = tmp_path / "external" / "codex"
    monkeypatch.setenv("CODEX_HOME", str(external))
    location = resolve_state_location(
        ROOT, "codex/codex-cli", cwd=cwd, home=tmp_path / "home", scope="global"
    )
    assert location.owner_root == external and location.root == external / "state"


@pytest.mark.parametrize("node_kind", ["file", "symlink", "directory"])
def test_multicomponent_global_intermediate_uses_registered_opencode_shape(
    tmp_path: Path, node_kind: str
) -> None:
    cwd = tmp_path / "plain"
    cwd.mkdir()
    home = tmp_path / "home"
    intermediate = home / ".config" / "opencode"
    intermediate.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    if node_kind == "file":
        intermediate.write_bytes(b"foreign\n")
    elif node_kind == "symlink":
        outside.mkdir()
        intermediate.symlink_to(outside, target_is_directory=True)
    else:
        intermediate.mkdir()

    if node_kind == "directory":
        location = resolve_state_location(
            ROOT, "opencode/opencode-cli", cwd=cwd, home=home, scope="global"
        )
        assert location.root == intermediate / "state" and not location.root.exists()
    else:
        with pytest.raises(ClientStateError) as failure:
            resolve_state_location(
                ROOT, "opencode/opencode-cli", cwd=cwd, home=home, scope="global"
            )
        assert failure.value.code == "unsafe_state_path"
        assert not (outside / "state").exists()
        assert intermediate.is_symlink() if node_kind == "symlink" else intermediate.read_bytes() == b"foreign\n"


@pytest.mark.parametrize("operation", ["allocate", "verify"])
def test_state_parent_symlink_introduced_after_resolution_fails_refresh_without_foreign_write(
    tmp_path: Path, operation: str
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    artifact = None
    if operation == "verify":
        artifact = allocate_artifact(location, **artifact_options())["artifact"]
        location = resolve_state_location(
            ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home"
        )
    owner = repo / ".codex"
    if owner.exists():
        owner.rename(repo / ".codex-prior")
    outside = tmp_path / "outside"
    outside.mkdir()
    owner.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ClientStateError) as failure:
        if operation == "allocate":
            allocate_artifact(location, **artifact_options())
        else:
            assert artifact is not None
            verify_artifact(location, artifact, schema_path=SCHEMA)
    assert failure.value.code == "unsafe_state_path"
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("kind", ["missing", "file", "permission"])
def test_probe_directory_failures_are_typed_and_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    target = tmp_path / "private-target"
    if kind == "file":
        target.write_text("not a directory\n", encoding="utf-8")
    elif kind == "permission":
        original_resolve = Path.resolve

        def deny_resolve(path: Path, *args, **kwargs):
            if path == target:
                raise PermissionError("private permission detail")
            return original_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", deny_resolve)
    with pytest.raises(ClientStateError) as failure:
        probe_git_context(target)
    assert failure.value.code == "invalid_directory"
    assert str(target) not in str(failure.value)


def test_bare_repository_and_ambiguous_probe_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    with pytest.raises(ClientStateError, match="bare repositories"):
        probe_git_context(bare)

    failed = subprocess.CompletedProcess(["git"], 2, "", "permission denied")
    monkeypatch.setattr(locator, "_git", lambda *_args: failed)
    with pytest.raises(ClientStateError, match="ambiguous Git"):
        probe_git_context(tmp_path)


def test_unsupported_unknown_and_symlink_states_fail_closed(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    unsupported_repo = repository(tmp_path / "unsupported-repo")
    with pytest.raises(ClientStateError, match="no supported repo"):
        resolve_state_location(
            ROOT, "antigravity/antigravity-ide", cwd=unsupported_repo,
            home=tmp_path / "home", scope="repo",
        )
    with pytest.raises(ClientStateError, match="unknown or invalid"):
        resolve_state_location(ROOT, "missing/missing-cli", cwd=plain, home=tmp_path / "home")

    repo = repository(tmp_path / "repo")
    (repo / ".codex").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(ClientStateError, match="symlink"):
        resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")


def test_exact_git_exclude_plan_apply_and_concurrent_change(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    plan = plan_git_exclude(location)
    assert plan.action == "append"
    assert plan.entry == "/.codex/state/"
    applied = apply_git_exclude(plan)
    assert applied.action == "applied"
    assert location.git
    text = location.git.exclude_path.read_text(encoding="utf-8")
    assert text.endswith("/.codex/state/\n")
    assert plan_git_exclude(location).action == "already-ignored"

    other = resolve_state_location(ROOT, "claude-code/claude-code-cli", cwd=repo, home=tmp_path / "home")
    stale = plan_git_exclude(other)
    location.git.exclude_path.write_text(text + "/other/\n", encoding="utf-8")
    apply_git_exclude(stale)
    merged = location.git.exclude_path.read_text(encoding="utf-8")
    assert "/other/\n" in merged and "/.claude/state/\n" in merged


def test_existing_repo_ignore_needs_no_local_exclude_write(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    (repo / ".gitignore").write_text("/.codex/state/\n", encoding="utf-8")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    plan = plan_git_exclude(location)
    assert plan.action == "already-ignored"
    assert apply_git_exclude(plan) == plan


def test_artifact_allocation_is_exclusive_deterministic_and_private(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    now = datetime(2026, 7, 15, 16, 2, 3, 456789, tzinfo=timezone.utc)
    first = allocate_artifact(
        location,
        content=b"checkpoint\n",
        agent="controller",
        purpose="release-checkpoint",
        extension="md",
        kind="restart-artifact",
        schema="restart-v1",
        producer="codex-controller",
        consumers=["codex", "codex"],
        now=now,
    )
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    second = allocate_artifact(
        location,
        content=b"next\n",
        agent="controller",
        purpose="release-checkpoint",
        extension="md",
        kind="restart-artifact",
        schema="restart-v1",
        producer="codex-controller",
        now=now,
    )
    assert first["artifact"] == "controller-20260715T160203456Z-release-checkpoint.md"
    assert second["artifact"] == "controller-20260715T160203456Z-release-checkpoint-01.md"
    encoded = json.dumps(first)
    assert str(repo) not in encoded and str(tmp_path) not in encoded
    assert first["record"]["repository"]["root"] == "."
    assert first["record"]["content"]["sha256"]
    assert first["record"]["consumers"] == ["codex"]


@pytest.mark.parametrize("field", ["predecessor", "checkpoint"])
def test_relative_metadata_length_boundary_is_prevalidated(
    tmp_path: Path, field: str
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    accepted = prepare_artifact_request(
        location, content=b"boundary\n", purpose="boundary", extension="md",
        kind="restart-artifact", schema="restart-v1", producer="controller",
        **{field: "a" * 512},
    )
    allocated = allocate_artifact(location, prepared=accepted)
    assert verify_artifact(location, allocated["artifact"], schema_path=SCHEMA)["ok"]

    current = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    with pytest.raises(ClientStateError) as failure:
        prepare_artifact_request(
            current, content=b"", purpose="boundary", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
            **{field: "a" * 513},
        )
    assert failure.value.code == f"invalid_{field}"


def test_relative_metadata_schema_matches_runtime_normalization(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    allocated = allocate_artifact(
        location, content=b"schema\n", purpose="schema-path", extension="md",
        kind="restart-artifact", schema="restart-v1", producer="controller",
    )
    metadata_schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    for field in ("predecessor", "checkpoint"):
        for accepted in ACCEPTED_RELATIVE_PATHS:
            assert not artifacts._schema_issues(
                {**allocated["record"], field: accepted}, metadata_schema
            ), (field, accepted)
        for rejected in REJECTED_RELATIVE_PATHS:
            assert artifacts._schema_issues(
                {**allocated["record"], field: rejected}, metadata_schema
            ), (field, rejected)


@pytest.mark.parametrize("field", ["predecessor", "checkpoint"])
@pytest.mark.parametrize("value", ["foo/", "."])
def test_verify_rejects_non_normalized_path_in_tampered_metadata(
    tmp_path: Path, field: str, value: str
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    allocated = allocate_artifact(
        location, content=b"tamper\n", purpose="tampered-path", extension="md",
        kind="restart-artifact", schema="restart-v1", producer="controller",
    )
    metadata_path = location.root / allocated["metadata"]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata[field] = value
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(ClientStateError) as failure:
        verify_artifact(location, allocated["artifact"], schema_path=SCHEMA)
    assert failure.value.code == "invalid_metadata"


def test_oversized_metadata_is_rejected_before_direct_api_mutation(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    consumers = [f"c{index:05d}-" + ("a" * 55) for index in range(18000)]
    with pytest.raises(ClientStateError) as failure:
        allocate_artifact(
            location, content=b"x\n", purpose="consumers", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
            consumers=reversed(consumers),
        )
    assert failure.value.code == "invalid_metadata"
    assert not (repo / ".codex" / "state").exists()


def test_explicit_global_scope_path_allocate_verify_from_deleted_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dead = tmp_path / "deleted-cwd"
    dead.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("CODEX_HOME", raising=False)
    prior_fd = os.open(".", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.chdir(dead)
        os.rmdir(dead)
        location = resolve_state_location(
            ROOT, "codex/codex-cli", cwd=Path("."), home=home, scope="global"
        )
        assert location.scope == "global" and location.cwd == ROOT
        allocated = allocate_artifact(
            location, content=b"global\n", purpose="deleted-cwd", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
        )
        assert verify_artifact(location, allocated["artifact"], schema_path=SCHEMA)["ok"]
    finally:
        os.fchdir(prior_fd)
        os.close(prior_fd)


def test_artifact_validation_and_stale_bindings(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    allocated = allocate_artifact(
        location,
        content=b"accepted\n",
        purpose="accepted-checkpoint",
        extension="json",
        kind="controller-ledger",
        schema="ledger-v1",
        producer="controller",
    )
    verified = verify_artifact(location, allocated["artifact"], schema_path=SCHEMA)
    assert verified["ok"] and verified["failures"] == []

    (location.root / allocated["artifact"]).write_bytes(b"tampered\n")
    verified = verify_artifact(location, allocated["artifact"], schema_path=SCHEMA)
    assert not verified["ok"] and "content hash mismatch" in verified["failures"]

    (repo / "tracked").write_text("two\n", encoding="utf-8")
    git(repo, "commit", "-qam", "advance")
    current = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    stale = verify_artifact(current, allocated["artifact"], schema_path=SCHEMA)
    assert "repository/ref snapshot is stale" in stale["failures"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("agent", "Bad Agent", "agent"),
        ("purpose", "../escape", "purpose"),
        ("extension", "md.exe", "extension"),
        ("predecessor", "../secret", "predecessor"),
    ],
)
def test_artifact_identity_and_paths_are_validated(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    kwargs = dict(
        content=b"",
        agent="worker",
        purpose="handoff",
        extension="md",
        kind="restart-artifact",
        schema="restart-v1",
        producer="worker",
    )
    kwargs[field] = value
    with pytest.raises(ClientStateError, match=message):
        allocate_artifact(location, **kwargs)


def test_state_root_inode_swap_is_rejected_before_write(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    state = repo / ".codex" / "state"
    state.mkdir(parents=True)
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    state.rename(repo / ".codex" / "prior-state")
    state.mkdir()
    with pytest.raises(ClientStateError, match="stale"):
        allocate_artifact(
            location, content=b"", purpose="handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
        )
    assert list(state.iterdir()) == []


def test_ineffective_whitespace_exclude_is_not_treated_as_covered(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    assert location.git
    location.git.exclude_path.write_text("  /.codex/state/\n", encoding="utf-8")
    plan = plan_git_exclude(location)
    assert plan.action == "append"
    apply_git_exclude(plan)
    assert plan_git_exclude(location).action == "already-ignored"


def test_stale_location_rejects_allocate_after_ref_advance(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    (repo / "tracked").write_text("advanced\n", encoding="utf-8")
    git(repo, "commit", "-qam", "advance")
    with pytest.raises(ClientStateError, match="stale"):
        allocate_artifact(
            location, content=b"", purpose="handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
        )
    assert not (repo / ".codex" / "state").exists()


@pytest.mark.parametrize(
    "value",
    [
        "agent-20260230T120000000Z-purpose.md",
        "agent-20260715T250000000Z-purpose.md",
        "agent-20260715T120000000Z-purpose-00.md",
        "agent-20260715T12000000Z-purpose.md",
        "Agent-20260715T120000000Z-purpose.md",
    ],
)
def test_filename_parser_rejects_malformed_and_impossible_values(value: str) -> None:
    with pytest.raises(ClientStateError):
        parse_artifact_name(value)


@pytest.mark.parametrize("field", ["predecessor", "checkpoint"])
@pytest.mark.parametrize("value", ACCEPTED_RELATIVE_PATHS)
def test_metadata_paths_accept_normalized_posix_grammar(
    tmp_path: Path, field: str, value: str
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    prepared = prepare_artifact_request(
        location, content=b"", purpose="handoff", extension="md",
        kind="restart-artifact", schema="restart-v1", producer="controller",
        **{field: value},
    )
    assert getattr(prepared, field) == value


@pytest.mark.parametrize("field", ["predecessor", "checkpoint"])
@pytest.mark.parametrize("value", REJECTED_RELATIVE_PATHS)
def test_metadata_paths_reject_non_normalized_posix_grammar(
    tmp_path: Path, field: str, value: str
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    with pytest.raises(ClientStateError, match="POSIX-relative") as failure:
        prepare_artifact_request(
            location, content=b"", purpose="handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
            **{field: value},
        )
    assert failure.value.code == f"invalid_{field}"


@pytest.mark.parametrize("schema_kind", ["missing", "directory", "symlink", "unreadable"])
def test_metadata_schema_fails_closed(tmp_path: Path, schema_kind: str) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    schema = tmp_path / "schema.json"
    if schema_kind == "directory":
        schema.mkdir()
    elif schema_kind == "symlink":
        schema.symlink_to(SCHEMA)
    elif schema_kind == "unreadable":
        schema.write_text("{}\n", encoding="utf-8")
        schema.chmod(0)
    with pytest.raises(ClientStateError, match="schema"):
        prepare_artifact_request(
            location, content=b"", purpose="handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
            metadata_schema=schema,
        )


def test_same_key_registry_drift_invalidates_location(tmp_path: Path) -> None:
    source = registry_root(tmp_path / "source")
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(source, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    clients = source / "ls" / "config" / "clients.yaml"
    text = clients.read_text(encoding="utf-8")
    clients.write_text(text.replace("display_name: OpenAI Codex CLI", "display_name: OpenAI Codex Command Line", 1), encoding="utf-8")
    with pytest.raises(ClientStateError, match="stale"):
        allocate_artifact(
            location, content=b"", purpose="handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
        )


def test_state_root_swap_between_refresh_and_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    state = repo / ".codex" / "state"
    state.mkdir(parents=True)
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    original = artifacts._open_absolute_directory

    def swap_then_open(path: Path, *, create: bool) -> int:
        state.rename(repo / ".codex" / "prior-state")
        state.mkdir()
        return original(path, create=create)

    monkeypatch.setattr(artifacts, "_open_absolute_directory", swap_then_open)
    with pytest.raises(ClientStateError, match="stale"):
        allocate_artifact(
            location, content=b"", purpose="handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
        )
    assert list(state.iterdir()) == []


def test_metadata_timestamp_and_registry_digest_are_bound(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    allocated = allocate_artifact(
        location, content=b"bound\n", purpose="handoff", extension="md",
        kind="restart-artifact", schema="restart-v1", producer="controller",
        now=datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc),
    )
    client = allocated["record"]["client"]
    assert client["registry_schema_version"] == 1
    assert client["variant_digest"] == location.variant_digest
    sidecar = location.root / allocated["metadata"]
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata["created_at"] = "20260715T120001000Z"
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    current = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    result = verify_artifact(current, allocated["artifact"], schema_path=SCHEMA)
    assert result["failures"] == ["artifact timestamp mismatch"]


def test_state_root_swap_after_bound_write_is_rejected_and_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    state = repo / ".codex" / "state"
    state.mkdir(parents=True)
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    original = artifacts._exclusive_write
    calls = 0

    def swap_during_artifact(directory_fd: int, name: str, data: bytes):
        nonlocal calls
        calls += 1
        if calls == 2:
            state.rename(repo / ".codex" / "prior-state")
            state.mkdir()
        return original(directory_fd, name, data)

    monkeypatch.setattr(artifacts, "_exclusive_write", swap_during_artifact)
    with pytest.raises(ClientStateError, match="stale"):
        allocate_artifact(
            location, content=b"bound\n", purpose="handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
            now=datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc),
        )
    assert list(state.iterdir()) == []
    assert [path.name for path in (repo / ".codex" / "prior-state").iterdir()] == [
        ".localsetup-artifacts.lock"
    ]


def test_ref_advance_during_write_is_rejected_and_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    original = artifacts._exclusive_write
    calls = 0

    def advance_during_artifact(directory_fd: int, name: str, data: bytes):
        nonlocal calls
        calls += 1
        if calls == 2:
            (repo / "tracked").write_text("advanced during allocation\n", encoding="utf-8")
            git(repo, "commit", "-qam", "advance during allocation")
        return original(directory_fd, name, data)

    monkeypatch.setattr(artifacts, "_exclusive_write", advance_during_artifact)
    with pytest.raises(ClientStateError, match="stale"):
        allocate_artifact(
            location, content=b"bound\n", purpose="handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
        )
    assert [path.name for path in (repo / ".codex" / "state").iterdir()] == [
        ".localsetup-artifacts.lock"
    ]


def test_git_exclude_parent_swap_is_descriptor_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    plan = plan_git_exclude(location)
    assert location.git
    info = location.git.exclude_path.parent
    outside = tmp_path / "outside"
    outside.mkdir()
    original = git_exclude._open_directory

    def swap_after_open(path: Path, *, create: bool) -> int:
        directory_fd = original(path, create=create)
        info.rename(info.with_name("info-prior"))
        info.symlink_to(outside, target_is_directory=True)
        return directory_fd

    monkeypatch.setattr(git_exclude, "_open_directory", swap_after_open)
    with pytest.raises(ClientStateError, match="unsafe|binding"):
        apply_git_exclude(plan)
    assert not (outside / "exclude").exists()


def test_git_exclude_failed_postcheck_rolls_back_owned_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    plan = plan_git_exclude(location)
    assert location.git
    before = location.git.exclude_path.read_bytes()
    monkeypatch.setattr(git_exclude, "_effective_ignore", lambda *_args: False)
    with pytest.raises(ClientStateError, match="ineffective"):
        apply_git_exclude(plan)
    assert location.git.exclude_path.read_bytes() == before


def test_git_exclude_stale_lock_file_is_reusable(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    plan = plan_git_exclude(location)
    assert location.git
    lock = location.git.exclude_path.with_name(f"{location.git.exclude_path.name}.localsetup.lock")
    lock.write_bytes(b"stale process residue\n")
    assert apply_git_exclude(plan).action == "applied"


def test_git_exclude_short_write_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    plan = plan_git_exclude(location)
    assert location.git
    before = location.git.exclude_path.read_bytes()
    original = os.write
    injected = False

    def short_write(fd: int, data: bytes) -> int:
        nonlocal injected
        if not injected and b"/.codex/state/" in data:
            injected = True
            return original(fd, data[:-1])
        return original(fd, data)

    monkeypatch.setattr(git_exclude.os, "write", short_write)
    with pytest.raises(ClientStateError, match="incomplete"):
        apply_git_exclude(plan)
    assert location.git.exclude_path.read_bytes() == before


def test_git_exclude_foreign_append_is_preserved_and_digest_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    plan = plan_git_exclude(location)
    assert location.git
    exclude = location.git.exclude_path
    original = os.write
    injected = False

    def append_foreign_first(fd: int, data: bytes) -> int:
        nonlocal injected
        if not injected and b"/.codex/state/" in data:
            injected = True
            foreign_fd = os.open(exclude, os.O_WRONLY | os.O_APPEND)
            try:
                original(foreign_fd, b"/foreign/\n")
            finally:
                os.close(foreign_fd)
        return original(fd, data)

    monkeypatch.setattr(git_exclude.os, "write", append_foreign_first)
    applied = apply_git_exclude(plan)
    final = exclude.read_bytes()
    assert b"/foreign/\n" in final and b"/.codex/state/\n" in final
    import hashlib
    assert applied.expected_digest == hashlib.sha256(final).hexdigest()


def test_artifact_and_state_modes_are_exact_under_restrictive_umask(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    previous = os.umask(0o777)
    try:
        allocated = allocate_artifact(
            location, content=b"private\n", purpose="handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
        )
    finally:
        os.umask(previous)
    state = repo / ".codex" / "state"
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE((state / allocated["artifact"]).stat().st_mode) == 0o600
    assert stat.S_IMODE((state / allocated["metadata"]).stat().st_mode) == 0o600
    current = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    assert verify_artifact(current, allocated["artifact"], schema_path=SCHEMA)["ok"]


def test_interrupted_sidecar_write_cleans_pending_and_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    original = artifacts._exclusive_write
    calls = 0

    def interrupt_sidecar(directory_fd: int, name: str, data: bytes):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt
        return original(directory_fd, name, data)

    monkeypatch.setattr(artifacts, "_exclusive_write", interrupt_sidecar)
    with pytest.raises(KeyboardInterrupt):
        allocate_artifact(
            location, content=b"private\n", purpose="handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
        )
    assert [path.name for path in (repo / ".codex" / "state").iterdir()] == [
        ".localsetup-artifacts.lock"
    ]


def test_pending_receipt_recovers_owned_orphan_and_preserves_foreign_collision(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    state = repo / ".codex" / "state"
    state.mkdir(parents=True)
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    name = "controller-20260715T120000000Z-recovery.md"
    metadata_name = f"{name}.meta.json"
    content = b"owned orphan\n"
    metadata = b"{}\n"
    pending = artifacts._pending_payload(name, metadata_name, content, metadata)
    receipt = state / artifacts._pending_name(name)
    receipt.write_bytes(pending)
    receipt.chmod(0o600)
    artifact = state / name
    artifact.write_bytes(content)
    artifact.chmod(0o600)
    allocate_artifact(
        location, content=b"new\n", purpose="new-handoff", extension="md",
        kind="restart-artifact", schema="restart-v1", producer="controller",
    )
    assert not receipt.exists() and not artifact.exists()

    receipt.write_bytes(pending)
    receipt.chmod(0o600)
    artifact.write_bytes(b"foreign collision\n")
    artifact.chmod(0o600)
    current = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    with pytest.raises(ClientStateError, match="foreign"):
        allocate_artifact(
            current, content=b"next\n", purpose="next-handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
        )
    assert receipt.exists() and artifact.read_bytes() == b"foreign collision\n"


def test_directory_fsync_failure_is_ambiguous_and_next_run_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    original = os.fsync
    directory_calls = 0

    def fail_second_directory_fsync(fd: int) -> None:
        nonlocal directory_calls
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_calls += 1
            if directory_calls == 2:
                raise OSError("injected directory fsync failure")
        original(fd)

    monkeypatch.setattr(artifacts.os, "fsync", fail_second_directory_fsync)
    now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(ClientStateError) as failure:
        allocate_artifact(
            location, content=b"committed pair\n", purpose="recovery", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller", now=now,
        )
    assert failure.value.code == "artifact_commit_ambiguous"
    state = repo / ".codex" / "state"
    assert len(list(state.glob(".localsetup-pending-*"))) == 1

    monkeypatch.setattr(artifacts.os, "fsync", original)
    current = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    recovered = allocate_artifact(
        current, content=b"committed pair\n", purpose="recovery", extension="md",
        kind="restart-artifact", schema="restart-v1", producer="controller", now=now,
    )
    assert recovered["artifact"].endswith("-01.md")
    assert list(state.glob(".localsetup-pending-*")) == []
    assert (state / "codex-cli-20260715T120000000Z-recovery.md").exists()


def test_verify_rejects_root_swap_after_descriptor_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    allocated = allocate_artifact(
        location, content=b"verify me\n", purpose="verify", extension="md",
        kind="restart-artifact", schema="restart-v1", producer="controller",
    )
    current = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    state = repo / ".codex" / "state"
    original = artifacts._read_regular_with_identity
    reads = 0

    def swap_after_reads(directory_fd: int, name: str, *, maximum: int):
        nonlocal reads
        data = original(directory_fd, name, maximum=maximum)
        reads += 1
        if reads == 2:
            state.rename(repo / ".codex" / "prior-state")
            state.mkdir(mode=0o700)
        return data

    monkeypatch.setattr(artifacts, "_read_regular_with_identity", swap_after_reads)
    with pytest.raises(ClientStateError, match="stale"):
        verify_artifact(current, allocated["artifact"], schema_path=SCHEMA)


def test_git_exclude_foreign_tail_makes_failed_rollback_explicitly_ambiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    plan = plan_git_exclude(location)
    assert location.git
    exclude = location.git.exclude_path
    checks = 0

    def fail_after_foreign_append(_root: Path, _entry: str) -> bool:
        nonlocal checks
        checks += 1
        if checks == 2:
            with exclude.open("ab") as handle:
                handle.write(b"/foreign-after/\n")
            return False
        return False

    monkeypatch.setattr(git_exclude, "_effective_ignore", fail_after_foreign_append)
    with pytest.raises(ClientStateError) as failure:
        apply_git_exclude(plan)
    assert failure.value.code == "exclude_commit_ambiguous"
    final = exclude.read_bytes()
    assert b"/.codex/state/\n" in final and b"/foreign-after/\n" in final


def test_git_environment_overrides_cannot_redirect_f02(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "repo")
    foreign = repository(tmp_path / "foreign")
    sentinel = foreign / "sentinel"
    sentinel.write_text("unchanged\n", encoding="utf-8")
    before = sentinel.read_bytes()
    overrides = {
        "GIT_DIR": str(foreign / ".git"),
        "GIT_WORK_TREE": str(foreign),
        "GIT_COMMON_DIR": str(foreign / ".git"),
        "GIT_INDEX_FILE": str(foreign / ".git" / "index"),
        "GIT_NAMESPACE": "hostile",
        "GIT_OBJECT_DIRECTORY": str(foreign / ".git" / "objects"),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(foreign / ".git" / "objects"),
    }
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    assert location.git and location.git.root == repo
    apply_git_exclude(plan_git_exclude(location))
    assert sentinel.read_bytes() == before
    assert b"/.codex/state/" not in (foreign / ".git" / "info" / "exclude").read_bytes()


@pytest.mark.parametrize("target", ["artifact-lock", "exclude-lock", "exclude"])
def test_mutable_hardlinks_are_rejected_without_foreign_mutation(tmp_path: Path, target: str) -> None:
    repo = repository(tmp_path / "repo")
    foreign = tmp_path / "foreign"
    foreign.write_bytes(b"foreign bytes\n")
    if target == "artifact-lock":
        (repo / ".codex" / "state").mkdir(parents=True)
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    assert location.git
    if target == "artifact-lock":
        state = repo / ".codex" / "state"
        os.link(foreign, state / ".localsetup-artifacts.lock")
        with pytest.raises(ClientStateError, match="lock"):
            allocate_artifact(
                location, content=b"x", purpose="handoff", extension="md",
                kind="restart-artifact", schema="restart-v1", producer="controller",
            )
    elif target == "exclude-lock":
        plan = plan_git_exclude(location)
        os.link(foreign, location.git.exclude_path.with_name("exclude.localsetup.lock"))
        with pytest.raises(ClientStateError, match="single-link"):
            apply_git_exclude(plan)
    else:
        location.git.exclude_path.unlink()
        os.link(foreign, location.git.exclude_path)
        with pytest.raises(ClientStateError, match="single-link"):
            plan_git_exclude(location)
    assert foreign.read_bytes() == b"foreign bytes\n"


@pytest.mark.parametrize("target", ["artifact-lock", "exclude-lock", "exclude"])
def test_mutable_fifos_are_rejected_before_open(tmp_path: Path, target: str) -> None:
    repo = repository(tmp_path / "repo")
    if target == "artifact-lock":
        (repo / ".codex" / "state").mkdir(parents=True)
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    assert location.git
    if target == "artifact-lock":
        fifo = repo / ".codex" / "state" / ".localsetup-artifacts.lock"
        os.mkfifo(fifo)
        operation = lambda: allocate_artifact(
            location, content=b"x", purpose="handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
        )
    elif target == "exclude-lock":
        plan = plan_git_exclude(location)
        fifo = location.git.exclude_path.with_name("exclude.localsetup.lock")
        os.mkfifo(fifo)
        operation = lambda: apply_git_exclude(plan)
    else:
        location.git.exclude_path.unlink()
        os.mkfifo(location.git.exclude_path)
        operation = lambda: plan_git_exclude(location)
    with pytest.raises(ClientStateError, match="regular|lock"):
        operation()


@pytest.mark.parametrize("probe_number", [1, 2])
def test_late_git_info_redirect_is_rejected_after_ignore_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe_number: int
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    plan = plan_git_exclude(location)
    assert location.git
    info = location.git.exclude_path.parent
    outside = tmp_path / "outside"
    outside.mkdir()
    calls = 0

    def redirect(_root: Path, _entry: str) -> bool:
        nonlocal calls
        calls += 1
        if calls == probe_number:
            info.rename(info.with_name("info-prior"))
            info.symlink_to(outside, target_is_directory=True)
            (outside / "exclude").write_text("/.codex/state/\n", encoding="utf-8")
        return calls == probe_number

    monkeypatch.setattr(git_exclude, "_effective_ignore", redirect)
    with pytest.raises(ClientStateError, match="binding"):
        apply_git_exclude(plan)
    assert (outside / "exclude").read_bytes() == b"/.codex/state/\n"


@pytest.mark.parametrize("replacement", ["artifact", "metadata"])
def test_verify_rejects_same_byte_entry_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    allocated = allocate_artifact(
        location, content=b"stable\n", purpose="verify-swap", extension="md",
        kind="restart-artifact", schema="restart-v1", producer="controller",
    )
    current = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    target_name = allocated["artifact"] if replacement == "artifact" else allocated["metadata"]
    original = artifacts._read_regular_with_identity
    swapped = False

    def replace_after_read(directory_fd: int, name: str, *, maximum: int):
        nonlocal swapped
        result = original(directory_fd, name, maximum=maximum)
        if name == target_name and not swapped:
            swapped = True
            data = result[0]
            os.unlink(name, dir_fd=directory_fd)
            fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=directory_fd)
            try:
                os.write(fd, data)
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
        return result

    monkeypatch.setattr(artifacts, "_read_regular_with_identity", replace_after_read)
    with pytest.raises(ClientStateError) as failure:
        verify_artifact(current, allocated["artifact"], schema_path=SCHEMA)
    assert failure.value.code == "artifact_commit_ambiguous"


@pytest.mark.parametrize("replacement", ["artifact", "metadata"])
def test_verify_rejects_same_inode_identical_byte_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    allocated = allocate_artifact(
        location, content=b"stable\n", purpose="verify-rewrite", extension="md",
        kind="restart-artifact", schema="restart-v1", producer="controller",
    )
    current = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    target_name = allocated["artifact"] if replacement == "artifact" else allocated["metadata"]
    original = artifacts._read_regular_with_identity
    rewritten = False

    def rewrite_after_read(directory_fd: int, name: str, *, maximum: int):
        nonlocal rewritten
        result = original(directory_fd, name, maximum=maximum)
        if name == target_name and not rewritten:
            rewritten = True
            data, before = result
            after = before
            for _attempt in range(100):
                fd = os.open(
                    name, os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
                try:
                    offset = 0
                    while offset < len(data):
                        offset += os.write(fd, data[offset:])
                    os.fsync(fd)
                finally:
                    os.close(fd)
                after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if after.st_ctime_ns != before.st_ctime_ns:
                    break
            assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
            assert after.st_ctime_ns != before.st_ctime_ns
        return result

    monkeypatch.setattr(artifacts, "_read_regular_with_identity", rewrite_after_read)
    with pytest.raises(ClientStateError) as failure:
        verify_artifact(current, allocated["artifact"], schema_path=SCHEMA)
    assert failure.value.code == "artifact_commit_ambiguous"


def test_pending_receipt_limit_stops_at_101_without_reading_receipts(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    state = repo / ".codex" / "state"
    state.mkdir(parents=True)
    for index in range(101):
        receipt = state / f".localsetup-pending-agent-20260715T120000000Z-p{index:03d}.md.json"
        receipt.write_bytes(b"not parsed\n")
        receipt.chmod(0o600)
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    with pytest.raises(ClientStateError) as failure:
        allocate_artifact(
            location, content=b"x", purpose="handoff", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller",
        )
    assert failure.value.code == "artifact_recovery_required"
    assert len(list(state.glob(".localsetup-pending-*"))) == 101


@pytest.mark.parametrize("branch", ["metadata-collision", "metadata-exception", "stale-postcheck"])
def test_cleanup_preserves_foreign_replacements_and_reports_ambiguity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, branch: str
) -> None:
    repo = repository(tmp_path / "repo")
    location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    state = repo / ".codex" / "state"
    now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    artifact_name = "codex-cli-20260715T120000000Z-cleanup.md"
    metadata_name = f"{artifact_name}.meta.json"
    if branch == "metadata-collision":
        state.mkdir(parents=True)
        collision = state / metadata_name
        collision.write_bytes(b"foreign metadata collision\n")
        collision.chmod(0o600)
        location = resolve_state_location(ROOT, "codex/codex-cli", cwd=repo, home=tmp_path / "home")
    original_write = artifacts._exclusive_write

    def replace_then_fail(directory_fd: int, name: str, data: bytes):
        if name == metadata_name and branch in {"metadata-collision", "metadata-exception"}:
            victim = artifact_name if branch == "metadata-collision" else artifacts._pending_name(artifact_name)
            os.unlink(victim, dir_fd=directory_fd)
            fd = os.open(victim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=directory_fd)
            try:
                os.write(fd, b"foreign replacement\n")
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
            if branch == "metadata-exception":
                raise RuntimeError("injected metadata failure")
        return original_write(directory_fd, name, data)

    monkeypatch.setattr(artifacts, "_exclusive_write", replace_then_fail)
    if branch == "stale-postcheck":
        original_bound = artifacts._bound_location
        checks = 0

        def replace_metadata_then_stale(bound_location, directory_fd: int):
            nonlocal checks
            checks += 1
            if checks == 3:
                os.unlink(metadata_name, dir_fd=directory_fd)
                fd = os.open(metadata_name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=directory_fd)
                try:
                    os.write(fd, b"foreign replacement\n")
                    os.fchmod(fd, 0o600)
                finally:
                    os.close(fd)
                raise ClientStateError("client state binding is stale", code="stale_state_binding")
            return original_bound(bound_location, directory_fd)

        monkeypatch.setattr(artifacts, "_bound_location", replace_metadata_then_stale)
    with pytest.raises(ClientStateError) as failure:
        allocate_artifact(
            location, content=b"owned\n", purpose="cleanup", extension="md",
            kind="restart-artifact", schema="restart-v1", producer="controller", now=now,
        )
    assert failure.value.code == "artifact_commit_ambiguous"
    assert any(path.read_bytes() == b"foreign replacement\n" for path in state.iterdir() if path.is_file())
