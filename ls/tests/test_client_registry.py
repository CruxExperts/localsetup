from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ls.core.client_registry import (
    ClientRegistryError,
    load_client_registry,
    platform_rows,
    projection_matches,
    render_platforms_yaml,
    write_platforms_projection,
)


ROOT = Path(__file__).resolve().parents[2]


def _copy_config(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "ls" / "config", root / "ls" / "config")
    return root


def test_registry_distinguishes_families_variants_and_projection() -> None:
    registry = load_client_registry(ROOT)

    assert len(registry.families) == 14
    assert len(registry.variants()) == 17
    assert registry.variant("cursor", "cursor-agent-cli").data["kind"] == "cli"
    assert registry.variant("cursor", "cursor-ide").data["kind"] == "ide"
    assert [row["id"] for row in platform_rows(registry)] == [
        "codex",
        "claude-code",
        "cursor",
        "kilo",
        "opencode",
        "openclaw",
        "github-copilot-cli",
        "github-copilot-vscode",
        "cline-cli",
        "cline-vscode",
        "amp-cli",
        "goose-cli",
    ]


def test_projection_uses_corrected_codex_and_opencode_paths() -> None:
    rows = {row["id"]: row for row in platform_rows(load_client_registry(ROOT))}

    assert rows["codex"]["repo_paths"] == [".agents/skills"]
    assert rows["codex"]["global_paths"] == ["~/.agents/skills"]
    assert rows["opencode"]["repo_paths"] == [".opencode/skills"]
    assert rows["opencode"]["global_paths"] == ["~/.config/opencode/skills"]
    assert rows["cursor"]["repo_paths"] == [".agents/skills", ".cursor/skills"]
    assert rows["openclaw"]["repo_paths"] == [".agents/skills"]


def test_projection_write_is_stable_and_detects_drift(tmp_path: Path) -> None:
    root = _copy_config(tmp_path)
    registry = load_client_registry(root)
    path = root / "ls" / "config" / "platforms.yaml"

    write_platforms_projection(root, registry)
    first = path.read_bytes()
    assert first == render_platforms_yaml(registry)
    assert projection_matches(root, registry)

    write_platforms_projection(root, registry)
    assert path.read_bytes() == first
    path.write_bytes(first + b"# drift\n")
    assert not projection_matches(root, registry)


def test_registry_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    root = _copy_config(tmp_path)
    path = root / "ls" / "config" / "clients.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "schema_version: 1\n", encoding="utf-8")

    with pytest.raises(ClientRegistryError, match="duplicate key"):
        load_client_registry(root)


def test_registry_rejects_unknown_fields(tmp_path: Path) -> None:
    root = _copy_config(tmp_path)
    path = root / "ls" / "config" / "clients.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("schema_version: 1", "schema_version: 1\nunknown_field: true", 1),
        encoding="utf-8",
    )

    with pytest.raises(ClientRegistryError, match="unknown_field"):
        load_client_registry(root)


def test_registry_rejects_traversal_and_invalid_supported_state(tmp_path: Path) -> None:
    root = _copy_config(tmp_path)
    path = root / "ls" / "config" / "clients.yaml"
    text = path.read_text(encoding="utf-8").replace("'.agents/skills'", "'../skills'", 1)
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ClientRegistryError, match="parent path segments"):
        load_client_registry(root)

    shutil.rmtree(root)
    root = _copy_config(tmp_path)
    path = root / "ls" / "config" / "clients.yaml"
    text = path.read_text(encoding="utf-8").replace("path: '.codex/state'", "path: null", 1)
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ClientRegistryError, match="supported state requires a path"):
        load_client_registry(root)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("preserve_mode: true", "preserve_mode: false", "byte-preservation contract"),
        ("preserve_owner: true", "preserve_owner: false", "byte-preservation contract"),
        ("limits: {status: unverified}", "limits: {status: unverified, max_iterations: 25}", "numeric limits require verified"),
        ("limits: {status: unverified}", "limits: {status: verified}", "verified limits require"),
        ("permissions: {status: unverified, controls: []}", "permissions: {status: unverified, controls: ['unsafe']}", "must not define controls"),
        ("permissions: {status: supported, controls: ['managed settings', 'permission rules']}", "permissions: {status: supported, controls: []}", "supported permissions require"),
        ("executables: [claude]", "executables: []", "CLI variants require"),
        ("goal: {status: unverified, kind: unverified", "goal: {status: unsupported, kind: unverified", "status and kind must match"),
        ("path: '.codex/state'", "path: 'AGENTS.md/state'", "state path overlaps policy"),
        ("'$CODEX_HOME/config.toml'", "'$HOME/config.toml'", "scoped under the user home"),
        (
            "global: {status: unsupported, collision: unsupported, rollback: unsupported}",
            "global: {status: unsupported, encoding: utf-8, collision: unsupported, rollback: unsupported}",
            "must not define byte-placement fields",
        ),
        (
            "global: {status: settings-only, collision: manual, rollback: manual-settings}",
            "global: {status: settings-only, encoding: utf-8, collision: manual, rollback: manual-settings}",
            "must not define byte-placement fields",
        ),
    ],
)
def test_registry_rejects_r02_negative_probes(tmp_path: Path, old: str, new: str, message: str) -> None:
    root = _copy_config(tmp_path)
    path = root / "ls" / "config" / "clients.yaml"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ClientRegistryError, match=message):
        load_client_registry(root)


def test_registry_preserves_exact_researched_rows_and_is_deeply_immutable() -> None:
    registry = load_client_registry(ROOT)
    codex = registry.variant("codex", "codex-cli")
    antigravity = registry.variant("antigravity", "antigravity-ide")
    cursor_agent = registry.variant("cursor", "cursor-agent-cli")
    kilo = registry.variant("kilo", "kilo-cli")
    omp = registry.variant("omp", "omp-cli")

    assert codex.data["policy"]["global"]["paths"] == (
        "$CODEX_HOME/AGENTS.override.md",
        "$CODEX_HOME/AGENTS.md",
    )
    assert codex.data["config"]["global"]["paths"] == ("$CODEX_HOME/config.toml",)
    assert antigravity.data["policy"]["repo"]["paths"] == (".agents/rules", ".agent/rules")
    assert cursor_agent.data["skills"]["global"]["paths"] == ("~/.agents/skills", "~/.cursor/skills")
    assert kilo.data["config"]["global"]["paths"] == (
        "~/.config/kilo/kilo.json",
        "~/.config/kilo/kilo.jsonc",
    )
    assert omp.data["config"]["repo"]["paths"] == (".omp/config.yml",)
    assert omp.data["permissions"]["status"] == "supported"
    assert antigravity.data["policy"]["repo"]["status"] == "supported"
    assert antigravity.data["insertion"]["repo"]["status"] == "unverified"
    cursor_ide = registry.variant("cursor", "cursor-ide")
    assert cursor_ide.data["policy"]["repo"]["paths"] == (".cursor/rules", "AGENTS.md")
    assert cursor_ide.data["insertion"]["repo"]["status"] == "unverified"
    with pytest.raises(TypeError):
        codex.data["policy"]["global"]["paths"] = ()


def test_client_registry_cli_checks_and_generates_projection(tmp_path: Path) -> None:
    root = _copy_config(tmp_path)
    tool = ROOT / "ls" / "tools" / "localsetup.py"
    projection = root / "ls" / "config" / "platforms.yaml"
    projection.write_text("platforms: []\n", encoding="utf-8")

    check = subprocess.run(
        [sys.executable, str(tool), "--source-root", str(root), "client-registry", "check"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert check.returncode == 1
    assert '"projection_matches": false' in check.stdout

    generated = subprocess.run(
        [sys.executable, str(tool), "--source-root", str(root), "client-registry", "generate"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert generated.returncode == 0
    assert '"projection_matches": true' in generated.stdout
    assert projection_matches(root, load_client_registry(root))


def test_supported_discovery_can_leave_mixed_or_directory_insertion_unverified(tmp_path: Path) -> None:
    root = _copy_config(tmp_path)
    registry = load_client_registry(root)

    assert registry.variant("antigravity", "antigravity-ide").data["insertion"]["repo"]["status"] == "unverified"
    assert registry.variant("cursor", "cursor-ide").data["insertion"]["repo"]["status"] == "unverified"


def test_invalid_preservation_diagnostic_names_the_failed_condition(tmp_path: Path) -> None:
    root = _copy_config(tmp_path)
    path = root / "ls" / "config" / "clients.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("preserve_mode: true", "preserve_mode: false", 1), encoding="utf-8")

    with pytest.raises(ClientRegistryError, match="preserve_mode must be true"):
        load_client_registry(root)


def test_projection_rejects_symlinked_config_parent_escape(tmp_path: Path) -> None:
    root = _copy_config(tmp_path)
    outside = tmp_path / "outside-config"
    shutil.copytree(root / "ls" / "config", outside)
    shutil.rmtree(root / "ls" / "config")
    (root / "ls" / "config").symlink_to(outside, target_is_directory=True)
    registry = load_client_registry(root)
    destination = outside / "platforms.yaml"
    destination.unlink()

    with pytest.raises(ValueError, match="must not contain symlinks"):
        projection_matches(root, registry)
    with pytest.raises(ValueError, match="must not contain symlinks"):
        write_platforms_projection(root, registry)
    assert not destination.exists()
