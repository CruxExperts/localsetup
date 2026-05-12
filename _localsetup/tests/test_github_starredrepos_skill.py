from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "_localsetup" / "skills" / "ls-github-starredrepos"


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_github_starredrepos_skill_is_registered() -> None:
    skill_md = SKILL / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert frontmatter["name"] == "ls-github-starredrepos"
    assert "starred repositories archive" in frontmatter["description"]

    pack = yaml.safe_load((ROOT / "_localsetup" / "config" / "pack.yaml").read_text(encoding="utf-8"))
    assert "ls-github-starredrepos" in pack["packs"]["integrations"]

    smoke = yaml.safe_load((ROOT / "_localsetup" / "tests" / "skill_smoke_commands.yaml").read_text(encoding="utf-8"))
    assert smoke["ls-github-starredrepos"] == "node scripts/verify-starredrepos-state.mjs --help"


def test_github_starredrepos_required_files_exist() -> None:
    required = [
        "references/source-ledger.md",
        "references/architecture.md",
        "references/authenticated-github-context.md",
        "references/starred-repo-sync-runbook.md",
        "references/starredrepos-repository-contract.md",
        "references/storage-strategies.md",
        "references/scout-modes.md",
        "references/release-intelligence.md",
        "references/docs-archive.md",
        "references/api-cli-references.md",
        "references/node-runtime.md",
        "references/actions-automation.md",
        "references/security-privacy.md",
        "references/rate-limits-resilience.md",
        "references/troubleshooting.md",
        "references/update-procedure.md",
        "data/schema/manifest.schema.json",
        "data/schema/snapshot-diff.schema.json",
        "data/schema/repo-metadata.schema.json",
        "data/schema/scout-report.schema.json",
        "data/examples/manifest.example.json",
        "data/examples/snapshot-diff.example.json",
        "data/examples/repo-metadata.example.json",
        "data/examples/scout-report.example.json",
        "templates/scout-prompt.md",
        "templates/scout-result.md",
        "templates/repo-doc.md",
        "templates/archive-README.md",
        "templates/sync-summary.md",
        "templates/github-actions-starredrepos.yml",
        "scripts/verify-github-auth.mjs",
        "scripts/list-starred-repos.mjs",
        "scripts/sync-starredrepos.mjs",
        "scripts/scout-repo-metadata.mjs",
        "scripts/generate-starredrepos-docs.mjs",
        "scripts/verify-starredrepos-state.mjs",
    ]
    missing = [path for path in required if not (SKILL / path).is_file()]
    assert missing == []


def test_github_starredrepos_json_examples_parse_and_validate_shape() -> None:
    repo = load_json(SKILL / "data/examples/repo-metadata.example.json")
    assert repo["fullName"] == "octocat/Hello-World"
    assert repo["owner"] == "octocat"
    assert isinstance(repo["topics"], list)

    manifest = load_json(SKILL / "data/examples/manifest.example.json")
    assert manifest["schemaVersion"] == "1.0"
    assert manifest["repositoryCount"] == len(manifest["repositories"])
    assert manifest["repositories"][0]["fullName"] == repo["fullName"]

    diff = load_json(SKILL / "data/examples/snapshot-diff.example.json")
    assert diff["schemaVersion"] == "1.0"
    assert diff["added"] == ["octocat/Hello-World"]

    scout = load_json(SKILL / "data/examples/scout-report.example.json")
    assert scout["mode"] == "static"
    assert {claim["status"] for claim in scout["claims"]} <= {"verified", "unverified"}


def test_github_starredrepos_script_help_exits_cleanly() -> None:
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    scripts = [
        "verify-github-auth.mjs",
        "list-starred-repos.mjs",
        "sync-starredrepos.mjs",
        "scout-repo-metadata.mjs",
        "generate-starredrepos-docs.mjs",
        "verify-starredrepos-state.mjs",
    ]
    for script in scripts:
        result = subprocess.run(
            ["node", f"scripts/{script}", "--help"],
            cwd=SKILL,
            check=False,
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert "Usage:" in result.stdout


def test_github_starredrepos_source_ledger_dates_volatile_claims() -> None:
    text = (SKILL / "references/source-ledger.md").read_text(encoding="utf-8")
    assert "Accessed: 2026-05-12." in text
    assert "Planning Verification Pattern" in text
    assert "CruxExperts" not in text
    assert "22 starred" not in text
    for phrase in ["Verify `gh auth status", "Verify `gh api /versions", "Verify GraphQL star counts"]:
        assert phrase in text


def test_github_starredrepos_files_do_not_contain_token_like_strings() -> None:
    token_re = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|Bearer\s+[A-Za-z0-9_.-]{20,})\b")
    offenders: list[str] = []
    for base in [SKILL, ROOT / "_localsetup" / "docs" / "_generated"]:
        for path in base.glob("**/*"):
            if path.is_file() and path.suffix in {".json", ".md", ".mjs", ".yml"}:
                if token_re.search(path.read_text(encoding="utf-8")):
                    offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_github_starredrepos_data_files_are_not_ignored() -> None:
    required = [
        SKILL / "data/schema/manifest.schema.json",
        SKILL / "data/examples/manifest.example.json",
    ]
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", *[str(path.relative_to(ROOT)) for path in required]],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    listed = set(result.stdout.splitlines())
    assert {str(path.relative_to(ROOT)) for path in required} <= listed


def test_github_starredrepos_rejects_malicious_full_name(tmp_path: Path) -> None:
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    manifest = load_json(SKILL / "data/examples/manifest.example.json")
    manifest["repositories"][0]["fullName"] = "owner/repo/../../../../escape"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = subprocess.run(
        [
            "node",
            "scripts/generate-starredrepos-docs.mjs",
            "--manifest",
            str(manifest_path),
            "--out",
            str(tmp_path / "out"),
        ],
        cwd=SKILL,
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "must be exactly owner/name" in result.stderr
    assert not (tmp_path / "escape.md").exists()


def test_github_starredrepos_rejects_malicious_scout_full_name(tmp_path: Path) -> None:
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    report = load_json(SKILL / "data/examples/scout-report.example.json")
    report["fullName"] = "../escape"
    command = tmp_path / "scout-command.mjs"
    command.write_text(
        "#!/usr/bin/env node\n"
        f"process.stdout.write({json.dumps(json.dumps(report))});\n",
        encoding="utf-8",
    )
    command.chmod(0o700)
    result = subprocess.run(
        ["node", "scripts/scout-repo-metadata.mjs", "--input", "data/examples/repo-metadata.example.json", "--mode", "command"],
        cwd=SKILL,
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
        env={**dict(), **__import__("os").environ, "STARREDREPOS_SCOUT_COMMAND": f"node {command}"},
    )
    assert result.returncode != 0
    assert "must not be path traversal segments" in result.stderr


def test_github_starredrepos_honors_github_host_environment() -> None:
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = (
        "import { GITHUB_HOST, githubEnv } from './scripts/common.mjs';"
        "console.log(JSON.stringify({host:GITHUB_HOST, ghHost:githubEnv().GH_HOST}));"
    )
    for env_key in ("STARREDREPOS_GITHUB_HOST", "GH_HOST"):
        env = {**__import__("os").environ}
        env.pop("STARREDREPOS_GITHUB_HOST", None)
        env.pop("GH_HOST", None)
        env[env_key] = "ghe.example"
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=SKILL,
            check=False,
            text=True,
            capture_output=True,
            timeout=10,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload == {"host": "ghe.example", "ghHost": "ghe.example"}


def test_github_starredrepos_storage_mode_defaults_to_metadata() -> None:
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    text = (SKILL / "scripts/sync-starredrepos.mjs").read_text(encoding="utf-8")
    assert 'process.env.STARREDREPOS_STORAGE_MODE || "metadata"' in text
    assert "Submodule storage planning is documented but not implemented" in text


def test_github_starredrepos_redaction_helper_covers_github_tokens() -> None:
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = SKILL / "scripts/test_github_starredrepos_redaction.mjs"
    result = subprocess.run(
        ["node", str(script)],
        cwd=SKILL,
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
