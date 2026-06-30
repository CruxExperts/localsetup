import importlib.util
import json
import subprocess
import shutil
from pathlib import Path

import yaml

from _localsetup.core.baseline import classify_path
from _localsetup.core.baseline import tracked_files
from _localsetup.core.manifests import load_pack_config, load_platforms, validate_manifest_schemas
from _localsetup.core.skills import ALLOWED_SKILL_TAXONOMY_CLASSES
from _localsetup.core.skills import load_skill_catalog
from _localsetup.core.skills import selected_skill_names
from _localsetup.core.skills import skill_taxonomy_payload
from _localsetup.core.skills import validate_skill_catalog
from _localsetup.core.workflows import selected_workflow_names, validate_workflow_catalog
from _localsetup.core.workflows import load_workflow_catalog


ROOT = Path(__file__).resolve().parents[2]


def test_dependency_pr_validation_exercises_manifest_inputs() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pr-validation.yml").read_text(encoding="utf-8")
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    assert "dependency-manifest-validation:" in workflow
    assert "github.actor == 'dependabot[bot]'" in workflow
    assert "uv lock --check" in workflow
    assert "uv sync --frozen --all-groups" in workflow
    assert "uv run --frozen pytest" in workflow
    assert "package-ecosystem: uv" in dependabot
    assert "dependency-name: PGPy" not in dependabot


def test_skill_index_scrub_can_prune_dead_urls(tmp_path: Path) -> None:
    module_path = ROOT / "_localsetup" / "tools" / "skill_index_scrub.py"
    spec = importlib.util.spec_from_file_location("skill_index_scrub_under_test", module_path)
    assert spec is not None and spec.loader is not None
    scrub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scrub)

    index = tmp_path / "PUBLIC_SKILL_INDEX.yaml"
    index.write_text(
        """
schema_version: 2
updated: '2026-05-18T00:00:00Z'
skills:
- name: dead
  description: Removed upstream.
  url: https://example.invalid/dead
- name: transient
  description: Temporary upstream failure.
  url: https://example.invalid/transient
- name: network
  description: Temporary network failure.
  url: https://example.invalid/network
- name: fixable
  description: "Anthropic skill: placeholder."
  url: https://example.com/fixable
  summary_short: "Anthropic skill: placeholder."
  summary_long: "Anthropic skill: placeholder."
  quality_signals: {}
""",
        encoding="utf-8",
    )
    updated, pruned = scrub.apply_fixes(
        index,
        [
            {
                "name": "dead",
                "url": "https://example.invalid/dead",
                "url_live": False,
                "url_status": 404,
                "action": "dead_url",
            },
            {
                "name": "transient",
                "url": "https://example.invalid/transient",
                "url_live": False,
                "url_status": 503,
                "action": "dead_url",
            },
            {
                "name": "network",
                "url": "https://example.invalid/network",
                "url_live": False,
                "url_status": 0,
                "action": "dead_url",
            },
            {
                "name": "fixable",
                "url": "https://example.com/fixable",
                "url_live": True,
                "action": "fixable",
                "fetched_desc": "Real upstream description.",
            },
        ],
        prune_dead_urls=True,
    )

    payload = yaml.safe_load(index.read_text(encoding="utf-8"))
    assert updated == 1
    assert pruned == 1
    assert [skill["name"] for skill in payload["skills"]] == ["transient", "network", "fixable"]
    assert payload["skills"][2]["description"] == "Real upstream description."


def test_pack_manifest_loads() -> None:
    root = Path(__file__).resolve().parents[2]
    pack = load_pack_config(root)
    assert pack.pack_id == "localsetup"
    assert pack.namespace == "ls"
    assert pack.lockfile == ".localsetup/lock.json"
    assert "core" in pack.packs
    assert "experimental" in pack.packs


def test_platform_manifest_has_six_platforms() -> None:
    root = Path(__file__).resolve().parents[2]
    platforms = load_platforms(root)
    ids = {p.platform_id for p in platforms}
    assert ids == {"codex", "claude-code", "cursor", "kilo", "opencode", "openclaw"}


def test_manifest_schemas_reject_unknown_pack_and_platform_fields(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    root = tmp_path / "repo"
    shutil.copytree(source / "_localsetup" / "config", root / "_localsetup" / "config")
    pack_path = root / "_localsetup" / "config" / "pack.yaml"
    platforms_path = root / "_localsetup" / "config" / "platforms.yaml"
    pack_path.write_text(pack_path.read_text(encoding="utf-8") + "\nunknown_control_field: true\n", encoding="utf-8")
    platforms_path.write_text(
        platforms_path.read_text(encoding="utf-8").replace("    native_config: symlink_or_reference", "    native_config: symlink_or_reference\n    unknown_platform_field: true", 1),
        encoding="utf-8",
    )

    issues = validate_manifest_schemas(root)

    assert any("pack.yaml schema validation failed" in issue and "unknown_control_field" in issue for issue in issues)
    assert any("platforms.yaml schema validation failed" in issue and "unknown_platform_field" in issue for issue in issues)


def test_facts_json_aligns_with_live_version_and_catalogs() -> None:
    root = Path(__file__).resolve().parents[2]
    facts = json.loads((root / "_localsetup" / "docs" / "_generated" / "facts.json").read_text(encoding="utf-8"))
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    platforms = load_platforms(root)
    platform_ids = [p.platform_id for p in platforms]
    skill_count = len(list((root / "_localsetup" / "skills").glob("ls-*/SKILL.md")))
    workflow_count = len(load_workflow_catalog(root))

    assert facts["version"] == version
    assert facts["provenance"]["schema_version"] == 1
    assert facts["provenance"]["emitter"] == "generate-docs"
    assert facts["major_minor"] == ".".join(version.split(".")[:2])
    assert facts["platform_count"] == len(platform_ids)
    assert sorted(row["id"] for row in facts["platforms"]) == sorted(platform_ids)
    assert facts["skill_count"] == skill_count
    assert facts["workflow_count"] == workflow_count


def test_framework_docs_lifecycle_frontmatter_is_recursive() -> None:
    root = Path(__file__).resolve().parents[2]
    missing: list[str] = []
    stale: list[str] = []

    for path in sorted((root / "_localsetup" / "docs").glob("**/*.md")):
        rel = path.relative_to(root)
        if any(part in {"_generated", "local-context"} for part in rel.parts):
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            missing.append(str(rel))
            continue
        header = text.split("---", 2)[1]
        if "status:" not in header or "version:" not in header:
            missing.append(str(rel))
        if "version: 3.0" in header:
            stale.append(str(rel))

    assert missing == []
    assert stale == []


def test_catalog_validation_and_pack_selection() -> None:
    root = Path(__file__).resolve().parents[2]

    assert validate_skill_catalog(root) == []
    assert validate_workflow_catalog(root) == []
    assert "ls-context" in selected_skill_names(root, ["core"])
    assert "ls-cloudflare-dns" not in selected_skill_names(root, ["core"])
    assert "ls-workflow-ops-tmux-session" in selected_workflow_names(root, ["core"])
    assert "ls-workflow-tmux-terminal-mode" in selected_workflow_names(root, ["core"])
    assert "ls-workflow-ops-tmux-session" in selected_workflow_names(root, ["ops"])
    assert "ls-workflow-tmux-terminal-mode" in selected_workflow_names(root, ["ops"])
    assert "ls-system-info" in selected_skill_names(root, ["ops"])


def test_skill_taxonomy_covers_all_shipped_skills_and_allowed_classes() -> None:
    root = Path(__file__).resolve().parents[2]
    pack = load_pack_config(root)
    skill_names = {path.parent.name for path in (root / "_localsetup" / "skills").glob("ls-*/SKILL.md")}
    taxonomy = pack.skill_taxonomy

    assert set(taxonomy) == skill_names
    assert len(taxonomy) == 60
    assert {row["class"] for row in taxonomy.values()} <= ALLOWED_SKILL_TAXONOMY_CLASSES
    assert {row["owner_scope"] for row in taxonomy.values()} == {"skill"}


def test_skill_catalog_uses_taxonomy_sort_order_and_payload_fields() -> None:
    root = Path(__file__).resolve().parents[2]
    catalog = load_skill_catalog(root)
    sort_keys = [(skill.sort_priority, skill.name) for skill in catalog]
    payload = skill_taxonomy_payload(root)

    assert sort_keys == sorted(sort_keys)
    assert [row["id"] for row in payload["skills"]] == [skill.name for skill in catalog]
    assert payload["count"] == len(catalog) == 60
    assert payload["skills"][0]["sort_priority"] == 10
    assert {"class", "sort_priority", "tags", "owner_scope", "packs"} <= set(payload["skills"][0])


def test_agent_queue_example_yaml_has_expected_runtime_shape() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = yaml.safe_load((root / "_localsetup" / "config" / "agent_queue.example.yaml").read_text(encoding="utf-8"))

    assert payload["layout"] in {"flat", "structured"}
    assert payload["queue_path"] == ".agent/queue"
    assert payload["agent_trust_registry_path"] == "_localsetup/config/agent_trust_registry.yaml"
    assert set(payload["transports_enabled"]) == {"mail", "file_drop"}
    assert payload["version_mismatch_policy"] in {"warn", "block", "allow_log"}
    assert payload["post_ingest_mailbox"]
    assert payload["sealed_extension"].startswith(".")
    assert all(isinstance(pattern, str) and pattern for pattern in payload["ignore_globs"])
    assert payload["archive_retention_days"] > 0
    assert payload["archive_max_total_gb"] > 0


def test_skill_allowed_tools_frontmatter_is_space_separated() -> None:
    root = Path(__file__).resolve().parents[2]

    for skill_md in sorted((root / "_localsetup" / "skills").glob("ls-*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        frontmatter = text.split("---", 2)[1]
        metadata = yaml.safe_load(frontmatter) or {}
        allowed_tools = metadata.get("allowed-tools")
        if allowed_tools is None:
            continue

        assert isinstance(allowed_tools, str), skill_md
        assert "," not in allowed_tools, skill_md
        assert allowed_tools.split(), skill_md


def test_old_workflow_skill_references_are_cut_over() -> None:
    root = Path(__file__).resolve().parents[2]
    stale = [
        "ls-agentic-" + "prd-batch",
        "ls-agentic-" + "umbrella-queue",
        "ls-decision-tree-" + "workflow",
        "ls-tmux-shared-session-" + "workflow",
        "ls-publish-" + "workflow",
        "localsetup-publish-" + "workflow",
        "WORKFLOW_" + "INDEX.md",
        "MAINTENANCE_" + "WORKFLOW.md",
        "scripts/" + "publish",
    ]
    scanned_suffixes = {".md", ".mdc", ".yaml", ".json", ".py", ".sh", ".ps1"}
    offenders: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in scanned_suffixes:
            continue
        if any(part in {".git", ".codex", ".localsetup-maint", ".venv", ".venv-codex", "__pycache__"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in stale:
            if needle in text:
                offenders.append(f"{path.relative_to(root)}:{needle}")
    assert offenders == []


def test_active_templates_do_not_reference_old_agents_skill_root() -> None:
    root = Path(__file__).resolve().parents[2]
    scanned_suffixes = {".md", ".mdc", ".yaml", ".json", ".py", ".sh", ".ps1"}
    offenders: list[str] = []
    for base in (root / "_localsetup" / "templates", root / "_localsetup" / "skills"):
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in scanned_suffixes:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if ".agents/skills" in text:
                offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_baseline_file_classification() -> None:
    assert classify_path("_localsetup/skills/ls-context/SKILL.md") == "keep"
    assert classify_path("_localsetup/workflows/ls-workflow-ops-tmux-session/SKILL.md") == "keep"
    assert classify_path("_localsetup/docs/_generated/artifact-registry.json") == "generate"
    assert classify_path("_localsetup/docs/_generated/skill_aliases.json") == "generate"
    assert classify_path("_localsetup/docs/local-context/SECRETS_OVERVIEW.md") == "private-maintainer"
    assert classify_path("scripts/generate-doc-artifacts") == "private-maintainer"


def test_baseline_tracked_files_excludes_untracked_local_files(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    (root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)

    files = tracked_files(root)

    assert "tracked.txt" in files
    assert "untracked.txt" not in files


def test_generated_implementation_map_includes_workflow_sources() -> None:
    root = Path(__file__).resolve().parents[2]
    file_map = (root / "_localsetup" / "docs" / "_generated" / "implementation-file-map.md").read_text(
        encoding="utf-8"
    )

    assert "_localsetup/config/workflow.schema.json" in file_map
    assert "_localsetup/docs/_generated/workflow-catalog.json" in file_map
    assert "_localsetup/workflows/ls-workflow-ops-tmux-session/SKILL.md" in file_map
    assert "_localsetup/docs/local-context/" not in file_map
    assert ".localsetup-maint/" not in file_map


def test_verify_rules_wrapper_prefers_uv_project_venv() -> None:
    wrapper = (ROOT / "_localsetup" / "tools" / "verify_rules").read_text(encoding="utf-8")

    assert 'REPO_ROOT="$(cd "$ENGINE_DIR/.." && pwd)"' in wrapper
    assert '$REPO_ROOT/.venv/bin/python' in wrapper
    assert 'LOCALSETUP_PYTHON_BIN' in wrapper
