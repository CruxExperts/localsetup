from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from _localsetup.core.manifests import load_pack_config, load_platforms
from _localsetup.core.paths import PathValidationError
from _localsetup.core.skills import validate_skill_catalog
from _localsetup.core.workflows import validate_workflow_catalog
from _localsetup.tests.manifest_test_helpers import ROOT, make_workflow_validation_repo


def test_skill_frontmatter_schema_rejects_unknown_field(tmp_path: Path) -> None:
    root = make_workflow_validation_repo(tmp_path)
    shutil.copy2(ROOT / "_localsetup" / "config" / "skill-frontmatter.schema.json", root / "_localsetup" / "config" / "skill-frontmatter.schema.json")
    skill_md = root / "_localsetup" / "skills" / "ls-context" / "SKILL.md"
    skill_md.write_text("---\nname: ls-context\ndescription: Context.\nunknown: true\n---\n", encoding="utf-8")

    issues = validate_skill_catalog(root)

    assert any("frontmatter schema validation failed" in issue and "unknown" in issue for issue in issues)


def test_workflow_schema_rejects_unknown_field(tmp_path: Path) -> None:
    root = make_workflow_validation_repo(tmp_path)
    shutil.copy2(ROOT / "_localsetup" / "config" / "workflow.schema.json", root / "_localsetup" / "config" / "workflow.schema.json")
    workflow_path = root / "_localsetup" / "workflows" / "ls-workflow-demo" / "workflow.yaml"
    workflow_path.write_text(workflow_path.read_text(encoding="utf-8") + "\nunknown: true\n", encoding="utf-8")

    issues = validate_workflow_catalog(root)

    assert any("workflow.yaml schema validation failed" in issue and "unknown" in issue for issue in issues)


def test_workflow_catalog_rejects_alias_collision(tmp_path: Path) -> None:
    root = make_workflow_validation_repo(tmp_path)
    manifest = root / "_localsetup" / "workflows" / "ls-workflow-demo" / "workflow.yaml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace("aliases: [demo flow]", "aliases: [ls-context]"), encoding="utf-8")

    issues = validate_workflow_catalog(root)
    assert any("workflow alias conflicts" in issue for issue in issues)


def test_workflow_catalog_rejects_unsafe_required_paths(tmp_path: Path) -> None:
    root = make_workflow_validation_repo(tmp_path)
    manifest = root / "_localsetup" / "workflows" / "ls-workflow-demo" / "workflow.yaml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        text.replace("required_tools: []", "required_tools: [/bin/sh, 'C:\\\\Windows\\\\cmd.exe']")
        .replace("  - _localsetup/docs/README.md", "  - /etc/passwd\n  - ../escape.md\n  - ~/.ssh/config"),
        encoding="utf-8",
    )

    issues = validate_workflow_catalog(root)
    assert sum("workflow requires unsafe tool path" in issue for issue in issues) == 2
    assert sum("workflow requires unsafe doc path" in issue for issue in issues) == 3


def test_workflow_catalog_reports_missing_package_files(tmp_path: Path) -> None:
    root = make_workflow_validation_repo(tmp_path)
    workflow = root / "_localsetup" / "workflows" / "ls-workflow-demo"
    (workflow / "SKILL.md").unlink()
    (workflow / "workflow.yaml").unlink()

    issues = validate_workflow_catalog(root)
    assert any("missing workflow SKILL.md" in issue for issue in issues)
    assert any("missing workflow.yaml" in issue for issue in issues)


def test_workflow_catalog_rejects_missing_dependency_and_smoke(tmp_path: Path) -> None:
    root = make_workflow_validation_repo(tmp_path)
    manifest = root / "_localsetup" / "workflows" / "ls-workflow-demo" / "workflow.yaml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        text.replace("required_skills: []", "required_skills: [ls-missing]")
        .replace("smoke:\n  - id: docs\n    check: _localsetup/docs/README.md exists", "smoke: []"),
        encoding="utf-8",
    )

    issues = validate_workflow_catalog(root)
    assert any("workflow requires missing skill" in issue for issue in issues)
    assert any("workflow missing smoke row" in issue for issue in issues)


def test_workflow_catalog_rejects_duplicate_id_and_bad_package_name(tmp_path: Path) -> None:
    root = make_workflow_validation_repo(tmp_path)
    workflow2 = root / "_localsetup" / "workflows" / "ls-workflow-wrong"
    workflow2.mkdir()
    (workflow2 / "SKILL.md").write_text(
        "---\nname: ls-workflow-wrong\ndescription: Wrong workflow.\n---\n",
        encoding="utf-8",
    )
    (workflow2 / "workflow.yaml").write_text(
        (root / "_localsetup" / "workflows" / "ls-workflow-demo" / "workflow.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    issues = validate_workflow_catalog(root)
    assert any("duplicate workflow_id" in issue for issue in issues)
    assert any("workflow package/id mismatch" in issue for issue in issues)


def test_workflow_catalog_rejects_alias_that_matches_later_workflow_id(tmp_path: Path) -> None:
    root = make_workflow_validation_repo(tmp_path)
    manifest = root / "_localsetup" / "workflows" / "ls-workflow-demo" / "workflow.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("aliases: [demo flow]", "aliases: [zeta]"),
        encoding="utf-8",
    )
    workflow2 = root / "_localsetup" / "workflows" / "ls-workflow-zeta"
    workflow2.mkdir()
    (workflow2 / "SKILL.md").write_text(
        "---\nname: ls-workflow-zeta\ndescription: Zeta workflow.\n---\n",
        encoding="utf-8",
    )
    (workflow2 / "workflow.yaml").write_text(
        """
workflow_id: zeta
display_name: Zeta
aliases: [zeta flow]
invocation: Zeta only.
required_skills: []
required_tools: []
required_docs:
  - _localsetup/docs/README.md
gates: []
phases: []
validation: []
outputs:
  - Zeta output
smoke:
  - id: docs
    check: _localsetup/docs/README.md exists
migration: {}
""",
        encoding="utf-8",
    )

    issues = validate_workflow_catalog(root)
    assert any("workflow alias conflicts with reserved name" in issue for issue in issues)


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
  home: ~/.local/share/localsetup
  package_root: ~/.local/share/localsetup/packages
  registry: ~/.local/share/localsetup/registry.json
repo:
  lockfile: .localsetup/lock.json
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
  home: ~/.local/share/localsetup
  package_root: ~/.local/share/localsetup/packages
  registry: ~/.local/share/localsetup/registry.json
repo:
  lockfile: .localsetup/lock.json
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
    verify_rules: []
    rollback_targets: [".codex/skills"]
""",
        encoding="utf-8",
    )

    with pytest.raises(PathValidationError):
        load_platforms(root)
