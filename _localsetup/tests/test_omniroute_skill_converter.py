from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "_localsetup" / "skills" / "ls-omniroute-skill-converter" / "scripts" / "omniroute_skill_converter.py"


def load_converter():
    spec = importlib.util.spec_from_file_location("omniroute_skill_converter_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_skill(path: Path, name: str, *, extensions: dict | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    frontmatter: dict = {
        "name": name,
        "description": f"{name} fixture.",
        "metadata": {"version": "1.0"},
    }
    if extensions is not None:
        frontmatter["extensions"] = extensions
    (path / "SKILL.md").write_text("---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n# Fixture\n", encoding="utf-8")


def make_local_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "_localsetup" / "skills").mkdir(parents=True)
    (repo / "_localsetup" / "config").mkdir(parents=True)
    (repo / "_localsetup" / "config" / "pack.yaml").write_text(
        """
pack_id: localsetup
namespace: ls
version: 3
global:
  package_root: ~/.local/share/localsetup/packages
  registry: ~/.local/share/localsetup/registry.json
repo:
  lockfile: .localsetup/lock.json
optional_packs: []
packs: {}
workflow_packs: {}
distribution_channels: []
public_private:
  public_paths: []
  private_paths: []
extensions:
  skill_taxonomy:
    ls-omniroute-proxy:
      class: integrations
      sort_priority: 50
      tags: [omniroute, proxy]
      owner_scope: skill
""",
        encoding="utf-8",
    )
    return repo


def test_upstream_to_local_name_mapping() -> None:
    converter = load_converter()

    assert converter.upstream_to_local_name("omniroute") == "ls-omniroute"
    assert converter.upstream_to_local_name("omniroute-chat") == "ls-omniroute-chat"


def test_reads_upstream_skill_manifests_from_local_fixture(tmp_path: Path) -> None:
    converter = load_converter()
    source = tmp_path / "OmniRoute"
    write_skill(source / "skills" / "omniroute", "omniroute")
    write_skill(source / "skills" / "omniroute-chat", "omniroute-chat")

    skills, metadata = converter.read_upstream_skills(
        source_path=source,
        source_repo="https://example.invalid/OmniRoute.git",
        ref="main",
        timeout=5,
    )

    assert [skill.name for skill in skills] == ["omniroute", "omniroute-chat"]
    assert skills[0].path == "skills/omniroute/SKILL.md"
    assert len(skills[0].sha256) == 64
    assert metadata["skills_root"].endswith("OmniRoute/skills")


def test_reads_local_frontmatter_omniroute_extension(tmp_path: Path) -> None:
    converter = load_converter()
    repo = make_local_repo(tmp_path)
    write_skill(
        repo / "_localsetup" / "skills" / "ls-omniroute-chat",
        "ls-omniroute-chat",
        extensions={
            "omniroute": {
                "source_skill": "omniroute-chat",
                "source_sha256": "abc",
                "source_commit": "def",
            }
        },
    )

    [local] = converter.read_local_skills(repo)

    assert local.name == "ls-omniroute-chat"
    assert local.omniroute["source_skill"] == "omniroute-chat"


def test_classifies_missing_current_stale_local_only_and_untracked(tmp_path: Path) -> None:
    converter = load_converter()
    current_hash = "a" * 64
    stale_hash = "b" * 64
    upstream = [
        converter.UpstreamSkill("omniroute", "skills/omniroute/SKILL.md", current_hash, "commit1", "2026-05-24T00:00:00Z"),
        converter.UpstreamSkill("omniroute-chat", "skills/omniroute-chat/SKILL.md", current_hash, None, None),
        converter.UpstreamSkill("omniroute-tools", "skills/omniroute-tools/SKILL.md", stale_hash, "commit2", "2026-05-24T00:00:00Z"),
    ]
    local = [
        converter.LocalSkill(
            "ls-omniroute-chat",
            "_localsetup/skills/ls-omniroute-chat/SKILL.md",
            {},
            {"source_skill": "omniroute-chat", "source_sha256": current_hash},
            ["omniroute"],
        ),
        converter.LocalSkill(
            "ls-omniroute-tools",
            "_localsetup/skills/ls-omniroute-tools/SKILL.md",
            {},
            {"source_skill": "omniroute-tools", "source_sha256": "c" * 64, "source_commit": "commit1"},
            ["omniroute"],
        ),
        converter.LocalSkill(
            "ls-omniroute-removed",
            "_localsetup/skills/ls-omniroute-removed/SKILL.md",
            {},
            {"source_skill": "omniroute-removed", "source_sha256": "d" * 64},
            ["omniroute"],
        ),
        converter.LocalSkill("ls-omniroute-proxy", "_localsetup/skills/ls-omniroute-proxy/SKILL.md", {}, {}, ["omniroute"]),
    ]

    rows = converter.classify(upstream, local)
    statuses = {(row.status, row.upstream_skill, row.local_skill) for row in rows}

    assert ("missing-local", "omniroute", None) in statuses
    assert ("current", "omniroute-chat", "ls-omniroute-chat") in statuses
    assert ("stale-local", "omniroute-tools", "ls-omniroute-tools") in statuses
    assert ("local-only", "omniroute-removed", "ls-omniroute-removed") in statuses
    assert ("untracked-local", None, "ls-omniroute-proxy") in statuses


def test_json_and_markdown_report_output(tmp_path: Path) -> None:
    converter = load_converter()
    repo = make_local_repo(tmp_path)
    source = tmp_path / "OmniRoute"
    write_skill(source / "skills" / "omniroute", "omniroute")
    write_skill(repo / "_localsetup" / "skills" / "ls-omniroute-proxy", "ls-omniroute-proxy")

    args = Namespace(
        repo_root=str(repo),
        source_path=str(source),
        source_repo="https://example.invalid/OmniRoute.git",
        ref="main",
        timeout=5,
        include_regex=None,
        output="json",
        out=None,
    )
    report = converter.build_report(args)
    json_text = json.dumps(report)
    markdown = converter.render_markdown(report)

    assert '"missing-local"' in json_text
    assert "| missing-local | omniroute |" in markdown
    assert "| untracked-local |  | ls-omniroute-proxy |" in markdown


def test_freshness_summary_defaults_to_converted_skill_blockers_only() -> None:
    converter = load_converter()
    rows = [
        converter.ReportRow("missing-local", "omniroute", None, "ls-omniroute", "skills/omniroute/SKILL.md", "missing"),
        converter.ReportRow("untracked-local", None, "ls-omniroute-proxy", None, None, "untracked"),
        converter.ReportRow("current", "omniroute-chat", "ls-omniroute-chat", "ls-omniroute-chat", "skills/omniroute-chat/SKILL.md", "ok"),
    ]

    summary = converter.freshness_summary(rows)

    assert summary["fresh"] is True
    assert summary["blocking_count"] == 0


def test_freshness_summary_can_require_full_and_strict_validation() -> None:
    converter = load_converter()
    rows = [
        converter.ReportRow("missing-local", "omniroute", None, "ls-omniroute", "skills/omniroute/SKILL.md", "missing"),
        converter.ReportRow("untracked-local", None, "ls-omniroute-proxy", None, None, "untracked"),
    ]

    summary = converter.freshness_summary(rows, require_all_upstream=True, strict_untracked=True)

    assert summary["fresh"] is False
    assert summary["blocking_count"] == 2
    assert summary["blocking_statuses"] == ["local-only", "missing-local", "stale-local", "untracked-local"]


def test_freshness_command_exit_codes_for_policy(tmp_path: Path) -> None:
    converter = load_converter()
    repo = make_local_repo(tmp_path)
    source = tmp_path / "OmniRoute"
    write_skill(source / "skills" / "omniroute", "omniroute")
    write_skill(repo / "_localsetup" / "skills" / "ls-omniroute-proxy", "ls-omniroute-proxy")
    base_args = [
        "freshness",
        "--repo-root",
        str(repo),
        "--source-path",
        str(source),
        "--source-repo",
        "https://example.invalid/OmniRoute.git",
        "--output",
        "json",
    ]

    assert converter.main(base_args) == 0
    assert converter.main([*base_args, "--require-all-upstream"]) == 1
    assert converter.main([*base_args, "--strict-untracked"]) == 1
