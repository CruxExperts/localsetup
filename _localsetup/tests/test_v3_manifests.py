from pathlib import Path

import pytest

from _localsetup.v3.baseline import classify_path
from _localsetup.v3.manifests import load_pack_config, load_platforms
from _localsetup.v3.paths import PathValidationError
from _localsetup.v3.skills import selected_skill_names, validate_skill_catalog


def test_pack_manifest_loads() -> None:
    root = Path(__file__).resolve().parents[2]
    pack = load_pack_config(root)
    assert pack.pack_id == "localsetup"
    assert pack.namespace == "ls"
    assert pack.lockfile == "localsetup.lock.json"
    assert "core" in pack.packs
    assert "experimental" in pack.packs


def test_platform_manifest_has_six_platforms() -> None:
    root = Path(__file__).resolve().parents[2]
    platforms = load_platforms(root)
    ids = {p.platform_id for p in platforms}
    assert ids == {"codex", "claude-code", "cursor", "kilo", "opencode", "openclaw"}


def test_catalog_validation_and_pack_selection() -> None:
    root = Path(__file__).resolve().parents[2]

    assert validate_skill_catalog(root) == []
    assert "localsetup-context" in selected_skill_names(root, ["core"])
    assert "localsetup-cloudflare-dns" not in selected_skill_names(root, ["core"])


def test_baseline_file_classification() -> None:
    assert classify_path("_localsetup/skills/localsetup-context/SKILL.md") == "migrate"
    assert classify_path("_localsetup/docs/_generated/skill_aliases.json") == "generate"
    assert classify_path("scripts/generate-doc-artifacts") == "private-maintainer"


def test_pack_manifest_rejects_absolute_public_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    config = root / "_localsetup" / "config"
    config.mkdir(parents=True)
    (config / "pack.yaml").write_text(
        """
pack_id: localsetup
namespace: ls
version: 3
global:
  root: ~/.local/share/agents/skills/localsetup
  registry: ~/.local/share/agents/skills/localsetup/.localsetup-registry.json
repo:
  lockfile: localsetup.lock.json
packs: {}
public_private:
  public_paths:
    - /etc/passwd
  private_paths: []
""",
        encoding="utf-8",
    )

    with pytest.raises(PathValidationError):
        load_pack_config(root)


@pytest.mark.parametrize(
    "bad_path",
    [
        "C:/Users/example/localsetup",
        "C:\\Users\\example\\localsetup",
        "~user/localsetup",
        "~/../escape",
        "safe\\..\\escape",
        "safe/..\\escape",
    ],
)
def test_pack_manifest_rejects_unsafe_public_paths(tmp_path: Path, bad_path: str) -> None:
    root = tmp_path / "repo"
    config = root / "_localsetup" / "config"
    config.mkdir(parents=True)
    (config / "pack.yaml").write_text(
        f"""
pack_id: localsetup
namespace: ls
version: 3
global:
  root: ~/.local/share/agents/skills/localsetup
  registry: ~/.local/share/agents/skills/localsetup/.localsetup-registry.json
repo:
  lockfile: localsetup.lock.json
packs: {{}}
public_private:
  public_paths:
    - '{bad_path}'
  private_paths: []
""",
        encoding="utf-8",
    )

    with pytest.raises(PathValidationError):
        load_pack_config(root)


def test_platform_manifest_rejects_parent_traversal(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    config = root / "_localsetup" / "config"
    config.mkdir(parents=True)
    (config / "platforms.yaml").write_text(
        """
platforms:
  - id: codex
    repo_paths: ["../escape"]
    global_paths: ["~/.codex/skills"]
    memory_paths: ["~/.codex/memories"]
    verify_rules: []
    rollback_targets: [".codex/skills"]
""",
        encoding="utf-8",
    )

    with pytest.raises(PathValidationError):
        load_platforms(root)


@pytest.mark.parametrize(
    "bad_home",
    [
        "C:/Users/example/.codex/skills",
        "C:\\Users\\example\\.codex\\skills",
        "~user/.codex/skills",
        "~/../.codex/skills",
        "~/.codex\\..\\escape",
    ],
)
def test_platform_manifest_rejects_unsafe_home_paths(tmp_path: Path, bad_home: str) -> None:
    root = tmp_path / "repo"
    config = root / "_localsetup" / "config"
    config.mkdir(parents=True)
    (config / "platforms.yaml").write_text(
        f"""
platforms:
  - id: codex
    repo_paths: [".codex/skills"]
    global_paths: ['{bad_home}']
    memory_paths: ["~/.codex/memories"]
    verify_rules: []
    rollback_targets: [".codex/skills"]
""",
        encoding="utf-8",
    )

    with pytest.raises(PathValidationError):
        load_platforms(root)
