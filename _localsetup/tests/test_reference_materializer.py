from __future__ import annotations

import json
from pathlib import Path
import pytest

from _localsetup.core.reference_materializer import REFERENCE_BUNDLE_PATH
from _localsetup.core.reference_materializer import classify_reference
from _localsetup.core.reference_materializer import materialize_package_artifact
from _localsetup.core.reference_materializer import validate_materialized_package


def test_reference_classifier_covers_public_private_and_source_paths() -> None:
    assert classify_reference("_localsetup/docs/QUICKSTART.md").category == "public_doc"
    assert classify_reference("_localsetup/docs/_generated/plugin-packs.md").category == "generated_public_doc"
    assert classify_reference("_localsetup/docs/local-context/private.md").category == "private_doc"
    assert classify_reference("_localsetup/docs/audits/report.md").category == "private_doc"
    assert classify_reference("docs/private.md").category == "private_doc"
    assert classify_reference(".localsetup-maint/docs/plan.md").category == "private_maintenance"
    assert classify_reference("_localsetup/config/pack.yaml").category == "public_source_file"
    assert classify_reference("_localsetup/lib/internal.py").category == "source_only_metadata"
    assert classify_reference("../escape.md").category == "blocked_escape"
    assert classify_reference("_localsetup/docs/../../.localsetup-maint/secret.md").category == "blocked_escape"


def test_materializer_rewrites_markdown_refs_and_copies_public_doc_closure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    docs = repo / "_localsetup" / "docs"
    skill = repo / "_localsetup" / "skills" / "ls-demo"
    docs.mkdir(parents=True)
    skill.mkdir(parents=True)
    (repo / "_localsetup" / "config").mkdir(parents=True)
    (repo / "_localsetup" / "config" / "reference-bundle.schema.json").write_text(
        (Path(__file__).resolve().parents[1] / "config" / "reference-bundle.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (docs / "QUICKSTART.md").write_text("# Quickstart\n\nSee [Registry](PLATFORM_REGISTRY.md).\n", encoding="utf-8")
    (docs / "PLATFORM_REGISTRY.md").write_text("# Registry\n", encoding="utf-8")
    (skill / "SKILL.md").write_text(
        "---\nname: ls-demo\ndescription: Demo.\n---\n\n"
        "Read [_localsetup/docs/QUICKSTART.md](_localsetup/docs/QUICKSTART.md) and "
        "`../../docs/PLATFORM_REGISTRY.md`.\n\n"
        "```bash\ncat _localsetup/docs/QUICKSTART.md\n```\n",
        encoding="utf-8",
    )

    manifest = materialize_package_artifact(
        repo,
        skill,
        tmp_path / "out" / "ls-demo",
        package_name="ls-demo",
        package_type="skill",
        private_paths=[],
        emitter="test",
    )

    output = tmp_path / "out" / "ls-demo"
    text = (output / "SKILL.md").read_text(encoding="utf-8")
    assert "references/localsetup/docs/QUICKSTART.md" in text
    assert "`references/localsetup/docs/PLATFORM_REGISTRY.md`" in text
    assert "cat references/localsetup/docs/QUICKSTART.md" in text
    assert (output / "references/localsetup/docs/QUICKSTART.md").is_file()
    assert (output / "references/localsetup/docs/PLATFORM_REGISTRY.md").is_file()
    assert (output / REFERENCE_BUNDLE_PATH).is_file()
    assert manifest["validation"]["ok"] is True
    assert validate_materialized_package(output, repo_root=repo)["ok"] is True


def test_materializer_rejects_rewritten_public_doc_when_source_doc_is_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    skill = repo / "_localsetup" / "skills" / "ls-demo"
    (repo / "_localsetup" / "docs").mkdir(parents=True)
    (repo / "_localsetup" / "config").mkdir(parents=True)
    skill.mkdir(parents=True)
    (repo / "_localsetup" / "config" / "reference-bundle.schema.json").write_text(
        (Path(__file__).resolve().parents[1] / "config" / "reference-bundle.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text(
        "---\nname: ls-demo\ndescription: Demo.\n---\n\n"
        "Read [_localsetup/docs/MISSING.md](_localsetup/docs/MISSING.md).\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="rewrite target is missing"):
        materialize_package_artifact(
            repo,
            skill,
            tmp_path / "out" / "ls-demo",
            package_name="ls-demo",
            package_type="skill",
            private_paths=[],
            emitter="test",
        )

    output = tmp_path / "out" / "ls-demo"
    assert not (output / "references/localsetup/docs/MISSING.md").exists()
    validation = validate_materialized_package(output, repo_root=repo, check_digest=False)
    assert validation["ok"] is False
    assert any("rewrite target is missing" in issue for issue in validation["issues"])


def test_materializer_rejects_dangling_localsetup_absolute_paths(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    stale = tmp_path / "old" / "_localsetup" / "tools" / "missing"
    (package / "SKILL.md").write_text(f"Run `{stale}`.\n", encoding="utf-8")

    validation = validate_materialized_package(package, repo_root=tmp_path)

    assert validation["ok"] is False
    assert any("dangling Localsetup absolute path" in issue for issue in validation["issues"])


def test_materializer_rejects_forbidden_paths_in_python_files(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "helper.py").write_text('DOC = "_localsetup/docs/TOOLING_POLICY.md"\n', encoding="utf-8")

    validation = validate_materialized_package(package, repo_root=tmp_path)

    assert validation["ok"] is False
    assert any("forbidden Localsetup path reference in helper.py" in issue for issue in validation["issues"])


def test_validate_materialized_package_rejects_unrecorded_framework_source_paths(tmp_path: Path) -> None:
    package = tmp_path / "package"
    manifest = package / REFERENCE_BUNDLE_PATH
    manifest.parent.mkdir(parents=True)
    (package / "SKILL.md").write_text("Read `_localsetup/core/apply.py`.\n", encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materializer_version": 1,
                "classifier_version": 1,
                "package_name": "ls-demo",
                "package_type": "skill",
                "source_path": "_localsetup/skills/ls-demo",
                "source_commit": "unknown",
                "emitter": "test",
                "copied_refs": [],
                "rewrites": [],
                "excluded_refs": [],
                "source_only_metadata": [],
                "runtime_resolved": [],
                "validation": {"ok": True, "issues": []},
                "digest": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    validation = validate_materialized_package(package, check_digest=False)

    assert validation["ok"] is False
    assert any("forbidden Localsetup path reference in SKILL.md" in issue for issue in validation["issues"])


def test_materializer_records_framework_source_paths_as_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    skill = repo / "_localsetup" / "skills" / "ls-demo"
    (repo / "_localsetup" / "config").mkdir(parents=True)
    skill.mkdir(parents=True)
    (repo / "_localsetup" / "config" / "reference-bundle.schema.json").write_text(
        (Path(__file__).resolve().parents[1] / "config" / "reference-bundle.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text(
        "---\nname: ls-demo\ndescription: Demo.\n---\n\nRead `_localsetup/core/apply.py`.\n",
        encoding="utf-8",
    )

    manifest = materialize_package_artifact(
        repo,
        skill,
        tmp_path / "out" / "ls-demo",
        package_name="ls-demo",
        package_type="skill",
        private_paths=[],
        emitter="test",
    )

    assert {"path": "_localsetup/core/apply.py", "source": str(skill / "SKILL.md")} in manifest["source_only_metadata"]


def test_materializer_rejects_unrecorded_existing_source_absolute_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    skill = repo / "_localsetup" / "skills" / "ls-demo"
    tool = repo / "_localsetup" / "tools" / "tmux_ops"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (repo / "_localsetup" / "config").mkdir(parents=True)
    skill.mkdir(parents=True)
    (repo / "_localsetup" / "config" / "reference-bundle.schema.json").write_text(
        (Path(__file__).resolve().parents[1] / "config" / "reference-bundle.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text(
        "---\nname: ls-demo\ndescription: Demo.\n---\n\n"
        f"Run `{tool.resolve(strict=False)} pick`.\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unrecorded Localsetup absolute path"):
        materialize_package_artifact(
            repo,
            skill,
            tmp_path / "out" / "ls-demo",
            package_name="ls-demo",
            package_type="skill",
            private_paths=[],
            emitter="test",
        )


def test_materializer_rejects_dangling_package_root_absolute_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    package = tmp_path / "package"
    home = tmp_path / "home with spaces"
    package_root = home / ".local" / "share" / "localsetup" / "packages"
    package.mkdir(parents=True)
    (repo / "_localsetup" / "config").mkdir(parents=True)
    (repo / "_localsetup" / "config" / "pack.yaml").write_text(
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
  public_paths: []
  private_paths: []
""",
        encoding="utf-8",
    )
    stale = package_root / "ls-missing" / "SKILL.md"
    (package / "SKILL.md").write_text(f"Open `{stale}`.\n", encoding="utf-8")

    validation = validate_materialized_package(package, repo_root=repo, home=home, runtime_package_root=package_root)

    assert validation["ok"] is False
    assert any("dangling Localsetup absolute path" in issue for issue in validation["issues"])


def test_materializer_records_directory_like_doc_literals_as_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    skill = repo / "_localsetup" / "skills" / "ls-demo"
    (repo / "_localsetup" / "docs" / "_generated").mkdir(parents=True)
    (repo / "_localsetup" / "config").mkdir(parents=True)
    skill.mkdir(parents=True)
    (repo / "_localsetup" / "config" / "reference-bundle.schema.json").write_text(
        (Path(__file__).resolve().parents[1] / "config" / "reference-bundle.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text(
        "---\nname: ls-demo\ndescription: Demo.\n---\n\n"
        "Generated artifacts live under `_localsetup/docs/_generated/`.\n",
        encoding="utf-8",
    )

    manifest = materialize_package_artifact(
        repo,
        skill,
        tmp_path / "out" / "ls-demo",
        package_name="ls-demo",
        package_type="skill",
        private_paths=[],
        emitter="test",
    )

    assert {"path": "_localsetup/docs/_generated/", "source": str(skill / "SKILL.md")} in manifest["source_only_metadata"]


def test_materializer_rejects_doc_reference_with_embedded_parent_traversal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    skill = repo / "_localsetup" / "skills" / "ls-demo"
    (repo / "_localsetup" / "docs").mkdir(parents=True)
    (repo / ".localsetup-maint").mkdir(parents=True)
    (repo / "_localsetup" / "config").mkdir(parents=True)
    skill.mkdir(parents=True)
    (repo / ".localsetup-maint" / "secret.md").write_text("# Secret\n", encoding="utf-8")
    (repo / "_localsetup" / "config" / "reference-bundle.schema.json").write_text(
        (Path(__file__).resolve().parents[1] / "config" / "reference-bundle.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text(
        "---\nname: ls-demo\ndescription: Demo.\n---\n\n"
        "Read [Secret](_localsetup/docs/../../.localsetup-maint/secret.md).\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsafe runtime doc reference"):
        materialize_package_artifact(
            repo,
            skill,
            tmp_path / "out" / "ls-demo",
            package_name="ls-demo",
            package_type="skill",
            private_paths=[],
            emitter="test",
        )

    output = tmp_path / "out" / "ls-demo"
    assert not (output / "references/localsetup/.localsetup-maint/secret.md").exists()


@pytest.mark.parametrize(
    "body",
    [
        "Read `_localsetup/docs/../../.localsetup-maint/secret.md`.\n",
        "Read _localsetup/docs/../../.localsetup-maint/secret.md before continuing.\n",
    ],
)
def test_materializer_rejects_inline_and_bare_doc_reference_traversals(tmp_path: Path, body: str) -> None:
    repo = tmp_path / "repo"
    skill = repo / "_localsetup" / "skills" / "ls-demo"
    (repo / "_localsetup" / "docs").mkdir(parents=True)
    (repo / ".localsetup-maint").mkdir(parents=True)
    (repo / "_localsetup" / "config").mkdir(parents=True)
    skill.mkdir(parents=True)
    (repo / ".localsetup-maint" / "secret.md").write_text("# Secret\n", encoding="utf-8")
    (repo / "_localsetup" / "config" / "reference-bundle.schema.json").write_text(
        (Path(__file__).resolve().parents[1] / "config" / "reference-bundle.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text(
        "---\nname: ls-demo\ndescription: Demo.\n---\n\n" + body,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsafe runtime doc reference"):
        materialize_package_artifact(
            repo,
            skill,
            tmp_path / "out" / "ls-demo",
            package_name="ls-demo",
            package_type="skill",
            private_paths=[],
            emitter="test",
        )


def test_validate_materialized_package_rejects_manifest_reference_escapes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    skill = repo / "_localsetup" / "skills" / "ls-demo"
    (repo / "_localsetup" / "docs").mkdir(parents=True)
    (repo / "_localsetup" / "config").mkdir(parents=True)
    skill.mkdir(parents=True)
    (repo / "_localsetup" / "config" / "reference-bundle.schema.json").write_text(
        (Path(__file__).resolve().parents[1] / "config" / "reference-bundle.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text("---\nname: ls-demo\ndescription: Demo.\n---\n", encoding="utf-8")
    manifest = materialize_package_artifact(
        repo,
        skill,
        tmp_path / "out" / "ls-demo",
        package_name="ls-demo",
        package_type="skill",
        private_paths=[],
        emitter="test",
    )
    output = tmp_path / "out" / "ls-demo"
    manifest_path = output / REFERENCE_BUNDLE_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["copied_refs"] = ["_localsetup/docs/../config/pack.yaml"]
    manifest["rewrites"] = [
        {"file": "_localsetup/skills/ls-demo/SKILL.md", "from": "_localsetup/docs/../config/pack.yaml", "to": "references/localsetup/docs/../config/pack.yaml"}
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    validation = validate_materialized_package(output, repo_root=repo, check_digest=False)

    assert validation["ok"] is False
    assert any("copied_ref is not a public doc" in issue for issue in validation["issues"])
    assert any("rewrite target escapes bundled docs" in issue for issue in validation["issues"])


def test_materializer_records_workflow_required_docs_as_source_only_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workflow = repo / "_localsetup" / "workflows" / "ls-workflow-demo"
    (repo / "_localsetup" / "config").mkdir(parents=True)
    workflow.mkdir(parents=True)
    (repo / "_localsetup" / "config" / "reference-bundle.schema.json").write_text(
        (Path(__file__).resolve().parents[1] / "config" / "reference-bundle.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (workflow / "SKILL.md").write_text("---\nname: ls-workflow-demo\ndescription: Demo.\n---\n", encoding="utf-8")
    (repo / "_localsetup" / "docs").mkdir(parents=True)
    (repo / "_localsetup" / "docs" / "QUICKSTART.md").write_text("# Quickstart\n", encoding="utf-8")
    (workflow / "workflow.yaml").write_text(
        "id: demo\nname: Demo\nsummary: Demo\nrequired_docs:\n  - _localsetup/docs/QUICKSTART.md\n",
        encoding="utf-8",
    )

    materialize_package_artifact(
        repo,
        workflow,
        tmp_path / "out" / "ls-workflow-demo",
        package_name="ls-workflow-demo",
        package_type="workflow",
        private_paths=[],
        emitter="test",
    )

    manifest = json.loads(((tmp_path / "out" / "ls-workflow-demo") / REFERENCE_BUNDLE_PATH).read_text(encoding="utf-8"))
    assert manifest["source_only_metadata"] == [
        {"path": "_localsetup/docs/QUICKSTART.md", "source": "workflow.yaml.required_docs"}
    ]
    assert "_localsetup/docs/QUICKSTART.md" in (tmp_path / "out" / "ls-workflow-demo" / "workflow.yaml").read_text(encoding="utf-8")


def test_materializer_rewrites_localsetup_resolver_tokens(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    skill = repo / "_localsetup" / "skills" / "ls-demo"
    (repo / "_localsetup" / "docs" / "ops").mkdir(parents=True)
    (repo / "_localsetup" / "tools").mkdir(parents=True)
    (repo / "_localsetup" / "config").mkdir(parents=True)
    skill.mkdir(parents=True)
    (repo / "_localsetup" / "config" / "reference-bundle.schema.json").write_text(
        (Path(__file__).resolve().parents[1] / "config" / "reference-bundle.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo / "_localsetup" / "docs" / "ops" / "tmux-ops-managed.md").write_text("# Managed\n", encoding="utf-8")
    (repo / "_localsetup" / "tools" / "tmux_ops").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (skill / "SKILL.md").write_text(
        "---\nname: ls-demo\ndescription: Demo.\n---\n\n"
        "Read `localsetup://doc/ops/tmux-ops-managed.md`.\n"
        "Run `localsetup://tool/tmux_ops pick`.\n"
        "Open `localsetup://package/ls-context/SKILL.md`.\n",
        encoding="utf-8",
    )

    home = tmp_path / "home with spaces"
    package_root = home / ".local" / "share" / "localsetup" / "packages"

    manifest = materialize_package_artifact(
        repo,
        skill,
        tmp_path / "out" / "ls-demo",
        package_name="ls-demo",
        package_type="skill",
        private_paths=[],
        home=home,
        runtime_package_root=package_root,
        emitter="test",
    )

    text = (tmp_path / "out" / "ls-demo" / "SKILL.md").read_text(encoding="utf-8")
    assert "localsetup://" not in text
    assert "references/localsetup/docs/ops/tmux-ops-managed.md" in text
    assert (tmp_path / "out" / "ls-demo" / "references" / "localsetup" / "docs" / "ops" / "tmux-ops-managed.md").is_file()
    assert str(repo / "_localsetup" / "tools" / "tmux_ops") in text
    assert str(package_root / "ls-context" / "SKILL.md") in text
    assert sorted(manifest["runtime_resolved"]) == sorted(
        [
            str(repo / "_localsetup" / "tools" / "tmux_ops"),
            str(package_root / "ls-context" / "SKILL.md"),
        ]
    )
    assert validate_materialized_package(
        tmp_path / "out" / "ls-demo",
        repo_root=repo,
        home=home,
        runtime_package_root=package_root,
    )["ok"] is True


def test_validate_materialized_package_rejects_unresolved_resolver_tokens(tmp_path: Path) -> None:
    package = tmp_path / "package"
    manifest = package / REFERENCE_BUNDLE_PATH
    manifest.parent.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        "---\nname: ls-demo\ndescription: Demo.\n---\n\nRun `localsetup://tool/tmux_ops pick`.\n",
        encoding="utf-8",
    )
    manifest.write_text('{"schema_version": 1, "digest": "0"}\n', encoding="utf-8")

    validation = validate_materialized_package(package, check_digest=False)

    assert validation["ok"] is False
    assert any("unresolved resolver token" in issue for issue in validation["issues"])


def test_materializer_rejects_private_workflow_required_docs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    workflow = repo / "_localsetup" / "workflows" / "ls-workflow-demo"
    (repo / "_localsetup" / "config").mkdir(parents=True)
    workflow.mkdir(parents=True)
    (workflow / "SKILL.md").write_text("---\nname: ls-workflow-demo\ndescription: Demo.\n---\n", encoding="utf-8")
    (workflow / "workflow.yaml").write_text(
        "id: demo\nname: Demo\nsummary: Demo\nrequired_docs:\n  - .localsetup-maint/docs/secret.md\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="workflow required_docs is not publishable"):
        materialize_package_artifact(
            repo,
            workflow,
            tmp_path / "out" / "ls-workflow-demo",
            package_name="ls-workflow-demo",
            package_type="workflow",
            private_paths=[],
            emitter="test",
        )

    assert not (tmp_path / "out" / "ls-workflow-demo" / "workflow.yaml").exists()


def test_validate_materialized_package_rejects_missing_manifest_fields(tmp_path: Path) -> None:
    package = tmp_path / "package"
    manifest = package / REFERENCE_BUNDLE_PATH
    manifest.parent.mkdir(parents=True)
    (package / "SKILL.md").write_text("---\nname: ls-demo\ndescription: Demo.\n---\n", encoding="utf-8")
    manifest.write_text('{"schema_version": 1, "digest": "0"}\n', encoding="utf-8")

    validation = validate_materialized_package(package)

    assert validation["ok"] is False
    assert any("reference bundle missing fields" in issue for issue in validation["issues"])


def test_validate_materialized_package_rejects_schema_invalid_manifest_shape(tmp_path: Path) -> None:
    package = tmp_path / "package"
    manifest = package / REFERENCE_BUNDLE_PATH
    manifest.parent.mkdir(parents=True)
    (package / "SKILL.md").write_text("---\nname: ls-demo\ndescription: Demo.\n---\n", encoding="utf-8")
    payload = {
        "schema_version": "1",
        "materializer_version": 1,
        "classifier_version": 1,
        "package_name": "ls-demo",
        "package_type": "invalid",
        "source_path": "_localsetup/skills/ls-demo",
        "source_commit": "unknown",
        "emitter": "test",
        "copied_refs": "_localsetup/docs/QUICKSTART.md",
        "rewrites": [],
        "excluded_refs": [],
        "source_only_metadata": [],
        "runtime_resolved": [],
        "validation": {"ok": True, "issues": []},
        "digest": "0" * 64,
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    validation = validate_materialized_package(package)

    assert validation["ok"] is False
    assert any("schema_version must be 1" in issue for issue in validation["issues"])
    assert any("package_type must be skill or workflow" in issue for issue in validation["issues"])
    assert any("copied_refs must be a string list" in issue for issue in validation["issues"])
