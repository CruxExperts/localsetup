from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

import run_framework_audit as audit  # noqa: E402


def test_sanitize_output_path_rejects_control_characters() -> None:
    try:
        audit._sanitize_output_path("/tmp/audit\nreport.md")
    except ValueError as exc:
        assert "control characters" in str(exc)
    else:
        raise AssertionError("expected ValueError for control character path")


def test_sanitize_output_path_rejects_long_component(tmp_path: Path) -> None:
    long_name = "a" * (audit.PATH_COMPONENT_MAX + 1)

    try:
        audit._sanitize_output_path(str(tmp_path / long_name))
    except ValueError as exc:
        assert "path component too long" in str(exc)
    else:
        raise AssertionError("expected ValueError for long path component")


def test_format_subprocess_failure_preserves_stdout_and_stderr() -> None:
    result = subprocess.CompletedProcess(
        args=["run_smoke.py"],
        returncode=7,
        stdout="first line\nsecond line\n",
        stderr="traceback-ish context\n",
    )

    message = audit._format_subprocess_failure("Skill matrix ls-example: smoke", result)

    assert "Skill matrix ls-example: smoke failed (exit 7)" in message
    assert "stdout:" in message
    assert "first line" in message
    assert "second line" in message
    assert "stderr:" in message
    assert "traceback-ish context" in message


def test_report_items_indent_multiline_evidence() -> None:
    lines: list[str] = []

    audit._append_report_items(lines, ["smoke failed\nstdout:\nboom"])

    assert lines == ["- smoke failed", "  stdout:", "  boom"]


def test_read_facts_version_uses_top_level_version(tmp_path: Path) -> None:
    facts = tmp_path / "_localsetup" / "docs" / "_generated" / "facts.json"
    facts.parent.mkdir(parents=True)
    facts.write_text(
        dedent(
            """\
            {
              "skills": [{"id": "ls-example", "version": "1.0"}],
              "version": "3.8.6"
            }
            """
        ),
        encoding="utf-8",
    )

    assert audit._read_facts_version(tmp_path) == "3.8.6"


def test_framework_root_resolves_installed_package_source_layout(tmp_path: Path) -> None:
    installed_script_dir = tmp_path / "localsetup" / "packages" / "ls-framework-audit" / "scripts"
    installed_script_dir.mkdir(parents=True)
    framework = tmp_path / "localsetup" / "source" / "_localsetup"
    (framework / "lib").mkdir(parents=True)
    (framework / "lib" / "deps.py").write_text("# placeholder\n", encoding="utf-8")

    assert audit._select_framework_root(installed_script_dir) == framework.resolve()


def test_installed_package_script_imports_support_lib_from_source_layout(tmp_path: Path) -> None:
    installed_script_dir = tmp_path / "localsetup" / "packages" / "ls-framework-audit" / "scripts"
    installed_script_dir.mkdir(parents=True)
    script = installed_script_dir / "run_framework_audit.py"
    shutil.copy2(SCRIPT_ROOT / "run_framework_audit.py", script)
    framework = tmp_path / "localsetup" / "source" / "_localsetup"
    (framework / "lib").mkdir(parents=True)
    (framework / "lib" / "deps.py").write_text(
        "def require_deps(names):\n    return None\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "--repo-root" in result.stdout
    assert "--framework-root" in result.stdout


def test_repo_root_defaults_to_caller_cwd_with_repo_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "consumer"
    nested = repo / "tools"
    (repo / ".localsetup").mkdir(parents=True)
    (repo / ".localsetup" / "lock.json").write_text("{}\n", encoding="utf-8")
    nested.mkdir()
    monkeypatch.chdir(nested)

    assert audit._repo_root() == repo.resolve()


def test_repo_root_from_framework_subdirectory_uses_containing_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    script_dir = repo / "_localsetup" / "skills" / "ls-framework-audit" / "scripts"
    script_dir.mkdir(parents=True)
    (repo / "_localsetup" / "README.md").write_text("# Framework\n", encoding="utf-8")
    (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
    monkeypatch.chdir(script_dir)

    assert audit._repo_root() == repo.resolve()


def test_main_honors_explicit_repo_root_and_framework_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "consumer"
    framework = tmp_path / "framework" / "_localsetup"
    repo.mkdir()
    framework.mkdir(parents=True)
    seen: dict[str, tuple[Path, ...]] = {}

    def fake_doc_checks(root: Path, fw: Path) -> list[str]:
        seen["doc"] = (root, fw)
        return []

    monkeypatch.setattr(audit, "phase_doc_checks", fake_doc_checks)
    monkeypatch.setattr(audit, "phase_link_checks", lambda root: [])
    monkeypatch.setattr(audit, "phase_skill_matrix", lambda root, fw: ([], []))
    monkeypatch.setattr(audit, "phase_version_facts", lambda root: ([], []))
    monkeypatch.setattr(audit, "phase_maintainer_refs", lambda root: [])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_framework_audit.py",
            "--repo-root",
            str(repo),
            "--framework-root",
            str(framework),
        ],
    )

    assert audit.main() == 0
    assert capsys.readouterr().out.strip() == "Errors: 0, Warnings: 0"
    assert seen["doc"] == (repo.resolve(), framework.resolve())


@pytest.mark.parametrize(
    "runtime_path",
    [
        Path(".codex/runs/ledger.md"),
        Path(".codex/sessions/session.md"),
        Path(".codex/logs/log.md"),
        Path(".codex/tmp/scratch.md"),
        Path(".localsetup-maint/audit.md"),
        Path("graphify-out/report.md"),
        Path("state/report.md"),
        Path("data/report.md"),
    ],
)
def test_maintainer_ref_scan_skips_private_runtime_paths(tmp_path: Path, runtime_path: Path) -> None:
    public_doc = tmp_path / "README.md"
    private_doc = tmp_path / runtime_path
    private_doc.parent.mkdir(parents=True)
    public_doc.write_text("This mentions private maintainer context.\n", encoding="utf-8")
    private_doc.write_text("This mentions private maintainer context.\n", encoding="utf-8")

    findings = audit.phase_maintainer_refs(tmp_path)

    assert findings == ["README.md:1: This mentions private maintainer context."]


def test_doc_checks_distinguish_target_and_framework_missing_paths(tmp_path: Path) -> None:
    repo = tmp_path / "consumer"
    framework = tmp_path / "framework" / "_localsetup"
    repo.mkdir()
    framework.mkdir(parents=True)

    errors = audit.phase_doc_checks(repo, framework)

    assert "Missing target repo doc/path: VERSION" in errors
    assert "Missing target repo doc/path: README.md" in errors
    assert "Missing framework source doc/path: docs/VERSIONING.md" in errors
    assert "Missing framework source doc/path: README.md" in errors


def test_skill_matrix_requires_one_smoke_row_per_skill(tmp_path: Path) -> None:
    fw = tmp_path / "_localsetup"
    (fw / "skills" / "ls-present").mkdir(parents=True)
    (fw / "skills" / "ls-missing").mkdir(parents=True)
    (fw / "tests").mkdir(parents=True)
    (fw / "tests" / "skill_smoke_commands.yaml").write_text(
        dedent(
            """\
            ls-present: "N/A"
            """
        ),
        encoding="utf-8",
    )

    errors, warnings = audit.phase_skill_matrix(tmp_path, fw)

    assert warnings == []
    assert errors == [
        "skill_smoke_commands.yaml missing entries for skill dirs: ls-missing"
    ]


def test_skill_matrix_supports_repo_root_smoke_entries(tmp_path: Path) -> None:
    fw = tmp_path / "_localsetup"
    (fw / "skills" / "ls-present").mkdir(parents=True)
    sandbox_scripts = fw / "skills" / "ls-skill-sandbox-tester" / "scripts"
    sandbox_scripts.mkdir(parents=True)
    (sandbox_scripts / "create_sandbox.py").write_text("# placeholder\n", encoding="utf-8")
    (sandbox_scripts / "run_smoke.py").write_text("# placeholder\n", encoding="utf-8")
    (fw / "tests").mkdir(parents=True)
    (fw / "tests" / "skill_smoke_commands.yaml").write_text(
        dedent(
            """\
            ls-present:
              cwd: repo-root
              command: "python3 -c \\"from pathlib import Path; Path('repo-root-smoke.txt').write_text('ok')\\""
            ls-skill-sandbox-tester: "N/A"
            """
        ),
        encoding="utf-8",
    )

    errors, warnings = audit.phase_skill_matrix(tmp_path, fw)

    assert warnings == []
    assert errors == []
    assert (tmp_path / "repo-root-smoke.txt").read_text(encoding="utf-8") == "ok"


def test_skill_matrix_rejects_invalid_structured_smoke_entry(tmp_path: Path) -> None:
    fw = tmp_path / "_localsetup"
    (fw / "skills" / "ls-present").mkdir(parents=True)
    sandbox_scripts = fw / "skills" / "ls-skill-sandbox-tester" / "scripts"
    sandbox_scripts.mkdir(parents=True)
    (sandbox_scripts / "create_sandbox.py").write_text("# placeholder\n", encoding="utf-8")
    (sandbox_scripts / "run_smoke.py").write_text("# placeholder\n", encoding="utf-8")
    (fw / "tests").mkdir(parents=True)
    (fw / "tests" / "skill_smoke_commands.yaml").write_text(
        dedent(
            """\
            ls-present:
              cwd: elsewhere
              command: "python3 -V"
            ls-skill-sandbox-tester: "N/A"
            """
        ),
        encoding="utf-8",
    )

    errors, warnings = audit.phase_skill_matrix(tmp_path, fw)

    assert warnings == []
    assert errors == [
        "Skill matrix ls-present: invalid smoke entry: mapping cwd must be 'skill-sandbox' or 'repo-root'"
    ]
