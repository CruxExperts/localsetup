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
    assert "cat _localsetup/docs/QUICKSTART.md" in text
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


def test_materializer_leaves_directory_like_doc_literals_unrewritten(tmp_path: Path) -> None:
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

    output = tmp_path / "out" / "ls-demo"
    assert "_localsetup/docs/_generated/" in (output / "SKILL.md").read_text(encoding="utf-8")
    assert manifest["copied_refs"] == []
    assert manifest["rewrites"] == []
    assert validate_materialized_package(output, repo_root=repo)["ok"] is True


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
