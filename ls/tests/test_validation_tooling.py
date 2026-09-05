import importlib.util
import sys
from pathlib import Path


def load_script_module(relative_path: str):
    root = Path(__file__).resolve().parents[2]
    script_path = root / relative_path
    module_name = "localsetup_test_" + "_".join(script_path.with_suffix("").parts[-4:])
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_skill_validation_scan(module, monkeypatch, skill_dir: Path, pattern_path: Path) -> int:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "skill_validation_scan.py",
            "--scan-root",
            str(skill_dir.parent),
            "--pattern-file",
            str(pattern_path),
            str(skill_dir),
        ],
    )
    return module.main()


def test_skill_validation_pattern_fallback_uses_canonical_repo(tmp_path, monkeypatch) -> None:
    module = load_script_module("ls/tools/skill_validation_scan.py")
    target = tmp_path / "docs" / "SKILL_VALIDATION_PATTERNS.yaml"
    fetched_urls: list[str] = []

    def fake_fetch_text(url: str) -> str:
        fetched_urls.append(url)
        return "updated: 2026-05-10T00:00:00Z\nprompt_injection: []\n"

    monkeypatch.setattr(module, "fetch_text", fake_fetch_text)

    ok, message = module.ensure_pattern_file(target, fetch_if_missing=True)
    expected_url = (
        "https://raw.githubusercontent.com/CruxExperts/localsetup/main/"
        "ls/docs/SKILL_VALIDATION_PATTERNS.yaml"
    )

    assert ok is True
    assert message == "fetched"
    assert fetched_urls == [expected_url]
    assert target.is_file()


def test_skill_validation_scan_stdout_omits_matched_content(tmp_path, monkeypatch, capsys) -> None:
    module = load_script_module("ls/tools/skill_validation_scan.py")
    skill_dir = tmp_path / "candidate"
    skill_dir.mkdir()
    pattern_path = tmp_path / "patterns.yaml"
    pattern_path.write_text("updated: 2099-01-01T00:00:00Z\n", encoding="utf-8")
    sensitive_match = "candidate-secret-must-not-appear"

    monkeypatch.setattr(module, "ensure_pattern_file", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(module, "load_patterns", lambda _path: [])
    monkeypatch.setattr(
        module,
        "scan_skill_dir",
        lambda *_args: (
            [
                {
                    "file": "SKILL.md",
                    "line": 7,
                    "col": 3,
                    "pattern_id": "prompt.example",
                    "matched": sensitive_match,
                    "description": "Potential hidden instruction",
                }
            ],
            False,
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "skill_validation_scan.py",
            "--scan-root",
            str(tmp_path),
            "--pattern-file",
            str(pattern_path),
            str(skill_dir),
        ],
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "file:SKILL.md line:7 col:3 pattern:prompt.example" in output
    assert "description:Potential hidden instruction" in output
    assert "matched:" not in output
    assert sensitive_match not in output


def test_skill_validation_scan_rejects_idless_pattern_without_echo(
    tmp_path, monkeypatch, capsys
) -> None:
    module = load_script_module("ls/tools/skill_validation_scan.py")
    skill_dir = tmp_path / "candidate"
    skill_dir.mkdir()
    sensitive_match = "idless-candidate-secret"
    (skill_dir / "SKILL.md").write_text(sensitive_match, encoding="utf-8")
    pattern_path = tmp_path / "patterns.yaml"
    pattern_path.write_text(
        "updated: '2099-01-01T00:00:00Z'\n"
        "prompt_injection:\n"
        "  - description: Synthetic missing-ID pattern\n"
        "    scope: skill_body\n"
        "    keywords:\n"
        f"      - {sensitive_match}\n",
        encoding="utf-8",
    )

    assert run_skill_validation_scan(module, monkeypatch, skill_dir, pattern_path) == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "Pattern prompt_injection[0] requires an id matching" in output
    assert "matched:" not in output
    assert sensitive_match not in output


def test_skill_validation_scan_rejects_oversized_candidate(tmp_path, monkeypatch, capsys) -> None:
    module = load_script_module("ls/tools/skill_validation_scan.py")
    skill_dir = tmp_path / "candidate"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "x" * (module.MAX_FILE_SIZE_BYTES + 1), encoding="utf-8"
    )
    pattern_path = tmp_path / "patterns.yaml"
    pattern_path.write_text("updated: '2099-01-01T00:00:00Z'\n", encoding="utf-8")

    assert run_skill_validation_scan(module, monkeypatch, skill_dir, pattern_path) == 1
    captured = capsys.readouterr()
    assert "candidate file exceeds 1048576-byte scan limit: SKILL.md" in captured.err
    assert "Content safety: No concerns" not in captured.out


def test_skill_validation_scan_propagates_candidate_stat_failure(
    tmp_path, monkeypatch, capsys
) -> None:
    module = load_script_module("ls/tools/skill_validation_scan.py")
    skill_dir = tmp_path / "candidate"
    skill_dir.mkdir()
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("candidate", encoding="utf-8")
    pattern_path = tmp_path / "patterns.yaml"
    pattern_path.write_text("updated: '2099-01-01T00:00:00Z'\n", encoding="utf-8")
    original_stat = Path.stat

    def fail_candidate_stat(path, *args, **kwargs):
        if path == skill_path:
            raise OSError("synthetic stat failure")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_candidate_stat)
    assert run_skill_validation_scan(module, monkeypatch, skill_dir, pattern_path) == 1
    captured = capsys.readouterr()
    assert "could not stat candidate file: SKILL.md" in captured.err
    assert "Content safety: No concerns" not in captured.out


def test_skill_validation_scan_propagates_candidate_read_failure(
    tmp_path, monkeypatch, capsys
) -> None:
    module = load_script_module("ls/tools/skill_validation_scan.py")
    skill_dir = tmp_path / "candidate"
    skill_dir.mkdir()
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("candidate", encoding="utf-8")
    pattern_path = tmp_path / "patterns.yaml"
    pattern_path.write_text("updated: '2099-01-01T00:00:00Z'\n", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_candidate_read(path, *args, **kwargs):
        if path == skill_path:
            raise OSError("synthetic read failure")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_candidate_read)
    assert run_skill_validation_scan(module, monkeypatch, skill_dir, pattern_path) == 1
    captured = capsys.readouterr()
    assert "could not read candidate file: SKILL.md" in captured.err
    assert "Content safety: No concerns" not in captured.out


def test_markdown_reference_validator_slugifies_gfm_punctuation() -> None:
    module = load_script_module(
        "ls/skills/ls-markdown-reference-validator/scripts/markdown_reference_validator.py"
    )

    assert module._slugify_heading("Stealth & Anti-Bot") == "stealth--anti-bot"


def test_strict_reference_profile_excludes_only_inert_upstream_source(tmp_path, monkeypatch) -> None:
    root = Path(__file__).resolve().parents[2]
    module = load_script_module(
        "ls/skills/ls-markdown-reference-validator/scripts/markdown_reference_validator.py"
    )
    monkeypatch.chdir(root)
    config = module._load_config(
        root / "ls/skills/ls-markdown-reference-validator/templates/markdown_reference_strict_repo.yaml"
    )
    archive = tmp_path / "ls/skills/ls-demo/references/upstream/demo"
    archive.mkdir(parents=True)
    snapshot = archive / "UPSTREAM_SKILL.source.md"
    authored = archive / "coverage.md"
    for path in (snapshot, authored):
        path.write_text("[Missing](../auxiliary/missing.md)\n", encoding="utf-8")

    findings, checked = module._extract_findings(
        [snapshot, authored], repo_root=tmp_path, inline_code_mode=config.inline_code_mode,
        ignore=config.ignore, max_findings=config.max_findings,
    )

    assert checked == 1
    assert [(finding.source_file, finding.category) for finding in findings] == [(str(authored), "missing_path")]


def test_markdown_reference_validator_profiles_load(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[2]
    module = load_script_module(
        "ls/skills/ls-markdown-reference-validator/scripts/markdown_reference_validator.py"
    )
    monkeypatch.chdir(root)
    template_dir = root / "ls" / "skills" / "ls-markdown-reference-validator" / "templates"

    configs = {
        path.name: module._load_config(path)
        for path in sorted(template_dir.glob("markdown_reference*.yaml"))
    }

    assert set(configs) == {
        "markdown_reference_audit.yaml",
        "markdown_reference_host_aware.yaml",
        "markdown_reference_strict_repo.yaml",
    }
    assert configs["markdown_reference_strict_repo.yaml"].report_path == (
        root / ".localsetup/state/markdown-reference/strict-repo.md"
    )
    assert configs["markdown_reference_host_aware.yaml"].report_path == (
        root / ".localsetup/state/markdown-reference/host-aware.md"
    )
    default_ignores = configs["markdown_reference_audit.yaml"].ignore.source_file_globs
    assert "**/docs/reference/markdown-reference-audit.md" in default_ignores
    assert "**/.localsetup/state/markdown-reference/**" in default_ignores

    default = configs["markdown_reference_audit.yaml"]
    assert default.report_path == root / ".localsetup/state/markdown-reference/default.md"
    assert default.state_file == root / ".localsetup/state/markdown-reference/default-last-run-epoch"
    assert all(target["base_dir"] == "{repo_root}" for target in default.targets)
    assert default.kilo_manifests == []


def test_markdown_reference_report_redacts_outside_repo_paths(tmp_path, monkeypatch) -> None:
    root = Path(__file__).resolve().parents[2]
    module = load_script_module("ls/skills/ls-markdown-reference-validator/scripts/markdown_reference_validator.py")
    monkeypatch.chdir(root)
    config = module._load_config(root / "ls/skills/ls-markdown-reference-validator/templates/markdown_reference_audit.yaml")
    config_module = sys.modules["markdown_reference_config"]
    outside = tmp_path.parent / "host confidential" / "secret.md"
    finding = config_module.Finding(str(outside), 1, "unreadable_source", str(outside), str(outside), f"Could not read source markdown: {outside}")
    discovery_module = sys.modules["markdown_reference_discovery"]
    manifest_note = discovery_module.ManifestNote
    report = module._render_report(config_path=outside, config=config, reason="test", files_scanned=[], checked_refs=1, findings=[finding], manifest_notes=[manifest_note("manifest-ok", outside)])
    assert str(outside) not in report
    assert outside.name not in report
    assert "<outside-repo>" in report
    assert ".localsetup/state/markdown-reference/default.md" in report

    in_repo_report = module._render_report(
        config_path=root / "validator.yaml",
        config=config,
        reason="test",
        files_scanned=[],
        checked_refs=0,
        findings=[],
        manifest_notes=[manifest_note("manifest-ok", Path("kilo.jsonc"))],
    )
    assert "manifest-ok:kilo.jsonc" in in_repo_report

    delimiter_path = tmp_path.parent / "private (scope)" / "kilo.jsonc"
    delimiter_report = module._render_report(
        config_path=outside,
        config=config,
        reason="test",
        files_scanned=[],
        checked_refs=0,
        findings=[],
        manifest_notes=[manifest_note("manifest-ok", delimiter_path)],
    )
    assert str(delimiter_path) not in delimiter_report
    assert "private (scope)" not in delimiter_report

    symlink_target_finding = config_module.Finding(
        str(root / "README.md"),
        1,
        "missing_path",
        str(outside),
        str(root / "README.md"),
        f"Resolved target through a symlink: {outside}",
    )
    symlink_target_report = module._render_report(
        config_path=root / "validator.yaml",
        config=config,
        reason="test",
        files_scanned=[],
        checked_refs=1,
        findings=[symlink_target_finding],
        manifest_notes=[],
    )
    assert str(outside) not in symlink_target_report
    assert "| missing_path | README.md | 1 | <outside-repo> | README.md |" in symlink_target_report
    assert "manifest-ok:<outside-repo>" in delimiter_report
