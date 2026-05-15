from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

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
