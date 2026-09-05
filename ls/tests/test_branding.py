from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from ls.core import branding
from ls.core.branding.cli import main
from ls.core.branding.rules import line_hash, references
from ls.core.branding.scanner import load_policy, scan


def policy() -> dict:
    return {"schema_version": 1, "exceptions": [], "visual_reviews": [], "binary_reviews": []}


def test_runtime_identity_uses_framework_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(branding, "framework_version", lambda: "12.3.4")
    assert branding.user_agent() == "LocalSetup/12.3.4"
    assert branding.CLI_NAME == "LSCli" and branding.CLI_COMMAND == "lscli"


def test_mixed_display_and_identifiers_are_classified_per_occurrence() -> None:
    rows = references("guide.md", "LocalSetup uses `localsetup doctor`; Localsetup is outdated.\nLocalSetup.")
    assert [r["classification"] for r in rows] == ["canonical", "technical", "unclassified", "canonical"]
    assert references("a.py", "from localsetup import cli")[0]["classification"] == "technical"
    assert references("a.md", "https://example.invalid/Localsetup/docs")[0]["classification"] == "technical"
    assert references("a.md", "LSCLI display")[0]["classification"] == "unclassified"
    assert references("a.md", "Localsetup-owned content")[0]["classification"] == "unclassified"
    for text in ("_Localsetup_", "__Localsetup__", "Localsetup/LSCli", "Localsetup/4.4.1"):
        assert references("a.md", text)[0]["classification"] == "unclassified"
    for text in ("LSCli/Localsetup", "LocalSetup/Localsetup", "LocalSetup/Localsetup.", "LSCli/Localsetup:"):
        assert references("a.md", text)[1]["classification"] == "unclassified"
    assert references("a.md", "LOCALSETUP_HOME")[0]["classification"] == "technical"
    assert references("a.md", "ls/docs/Localsetup.md")[0]["classification"] == "technical"


def test_exact_exceptions_expire_when_text_or_count_changes(tmp_path: Path) -> None:
    text = "Localsetup historical quote"
    (tmp_path / "history.md").write_text(text)
    settings = policy()
    settings["exceptions"] = [{"path": "history.md", "line_sha256": line_hash(text), "token": "Localsetup", "count": 1, "kind": "historical_evidence", "reason": "Exact dated upstream quotation."}]
    assert scan(tmp_path, settings, paths=["history.md"])["ok"]
    (tmp_path / "history.md").write_text(text + "\n" + text)
    result = scan(tmp_path, settings, paths=["history.md"])
    assert {f["code"] for f in result["findings"]} == {"stale_exception", "unclassified_reference"}
    (tmp_path / "history.md").write_text("LocalSetup historical quote")
    assert scan(tmp_path, settings, paths=["history.md"])["findings"][0]["code"] == "stale_exception"


def test_git_inventory_detects_new_files_and_generator_regression(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "guide.md").write_text("LocalSetup")
    subprocess.run(["git", "-C", str(tmp_path), "add", "guide.md"], check=True)
    (tmp_path / "new.md").write_text("Localsetup")
    generated = tmp_path / "ls/docs/_generated"
    generated.mkdir(parents=True)
    (generated / "guide.md").write_text("Localsetup")
    result = scan(tmp_path, policy())
    assert {f["path"] for f in result["findings"]} == {"new.md", "ls/docs/_generated/guide.md"}
    assert result["counts"]["files"] == 3


def test_visual_hash_change_invalidates_acceptance(tmp_path: Path) -> None:
    data = b"\x89PNG\x00fixture"
    (tmp_path / "hero.png").write_bytes(data)
    settings = policy()
    assert scan(tmp_path, settings, paths=["hero.png"])["findings"][0]["code"] == "visual_review_required"
    settings["visual_reviews"] = [{"path": "hero.png", "sha256": hashlib.sha256(data).hexdigest(), "reviewed_text": "LocalSetup", "accessibility_evidence": "README.md hero alt text", "reviewer": "test fixture", "reviewed_at": "2026-09-05"}]
    assert scan(tmp_path, settings, paths=["hero.png"])["ok"]
    (tmp_path / "hero.png").write_bytes(data + b"changed")
    assert {f["code"] for f in scan(tmp_path, settings, paths=["hero.png"])["findings"]} == {"stale_visual_review", "visual_review_required"}


def test_external_symlink_is_not_read(tmp_path: Path) -> None:
    (tmp_path / "outside").symlink_to("/not-a-readable-branding-source")
    result = scan(tmp_path, policy(), paths=["outside"])
    assert result["inventory"] == [{"path": "outside", "surface": "symlink", "ownership": "compatibility_link"}]


def test_unknown_binaries_require_classification_and_hidden_images_require_review(tmp_path: Path) -> None:
    (tmp_path / "image").write_bytes(b"BM\0fixture")
    (tmp_path / "data.bin").write_bytes(b"\0nonvisual")
    result = scan(tmp_path, policy(), paths=["image", "data.bin"])
    assert {f["code"] for f in result["findings"]} == {"visual_review_required", "binary_classification_required"}
    settings = policy()
    settings["binary_reviews"] = [{"path": "data.bin", "sha256": hashlib.sha256(b"\0nonvisual").hexdigest(), "reason": "Binary parser fixture, no rendered content."}]
    assert scan(tmp_path, settings, paths=["data.bin"])["ok"]
    (tmp_path / "data.bin").write_bytes(b"\0changed")
    assert scan(tmp_path, settings, paths=["data.bin"])["findings"][0]["code"] == "stale_binary_review"


def test_report_mode_is_not_a_compliance_claim(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "bad.md").write_text("Localsetup")
    settings = tmp_path / "policy.json"
    settings.write_text(json.dumps(policy()))
    args = ["--repo-root", str(tmp_path), "--policy", str(settings)]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert main([*args, "--strict"]) == 1


def test_policy_rejects_broad_or_unexplained_exceptions(tmp_path: Path) -> None:
    settings = policy()
    settings["exceptions"] = [{"path": "../outside", "reason": ""}]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(settings))
    with pytest.raises(ValueError, match="repository-relative"):
        load_policy(path)


def test_shell_fences_classify_only_executable_position() -> None:
    text = "```bash\nlocalsetup doctor # Localsetup display\necho localsetup\n```\nlocalsetup prose\n"
    assert [r["classification"] for r in references("guide.md", text)] == [
        "technical", "unclassified", "unclassified", "unclassified",
    ]
    assert references("guide.md", "```text\nlocalsetup prose\n```")[0]["classification"] == "unclassified"
    assert references("guide.md", "~~~sh\n$ lscli run\n~~~")[0]["classification"] == "technical"
    assert references("guide.md", "```sh\nlocalsetup-owned text\n```")[0]["classification"] == "unclassified"


def test_environment_punctuation_and_relative_filenames_preserve_mixed_display() -> None:
    text = '${LOCALSETUP_HOME:-/tmp} LOCALSETUP_OTHER. assets/localsetup-logo.png Localsetup display'
    assert [r["classification"] for r in references("guide.md", text)] == [
        "technical", "technical", "technical", "unclassified",
    ]
    for text in ("LOCALSETUP display", "Localsetup/LSCli", "localsetup-owned display"):
        assert references("guide.md", text)[0]["classification"] == "unclassified"


def test_shell_literal_bodies_and_console_output_remain_unclassified() -> None:
    for body in ("cat <<'EOF'\nlocalsetup is our framework.\nEOF", 'echo "\nlocalsetup display\n"'):
        assert references("guide.md", "```bash\n" + body + "\n```")[0]["classification"] == "unclassified"
    rows = references("guide.md", "```console\n$ localsetup doctor\nlocalsetup display\n```")
    assert [r["classification"] for r in rows] == ["technical", "unclassified"]


def test_policy_metadata_does_not_exempt_rationale_or_arbitrary_token_fields(tmp_path: Path) -> None:
    settings = policy()
    line = "Localsetup dated evidence"
    settings["exceptions"] = [{"path": "history.md", "line_sha256": line_hash(line), "token": "Localsetup", "count": 1, "kind": "historical_evidence", "reason": "Dated source spelling."}]
    (tmp_path / "history.md").write_text(line)
    owner = tmp_path / "ls/config/branding.json"
    owner.parent.mkdir(parents=True)
    owner.write_text(json.dumps(settings, indent=2) + "\n")
    paths = ["history.md", "ls/config/branding.json"]
    assert scan(tmp_path, settings, paths=paths)["ok"]
    settings["exceptions"][0]["reason"] = "Localsetup display rationale"
    owner.write_text(json.dumps(settings, indent=2) + "\n")
    result = scan(tmp_path, settings, paths=paths)
    assert len(result["findings"]) == 1
    assert result["findings"][0]["path"] == "ls/config/branding.json"
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"token": "Localsetup"}, indent=2))
    assert scan(tmp_path, policy(), paths=["other.json"])["findings"]
