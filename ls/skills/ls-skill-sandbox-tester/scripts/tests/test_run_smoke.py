from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
CREATE_PATH = SCRIPTS_DIR / "create_sandbox.py"
RUN_PATH = SCRIPTS_DIR / "run_smoke.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


create_sandbox = _load_module("create_sandbox_for_run_smoke_tests", CREATE_PATH)
run_smoke = _load_module("run_smoke", RUN_PATH)


def _make_sandbox(tmp_path: Path) -> Path:
    source = tmp_path / "source" / "ls-example-skill"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: ls-example-skill\ndescription: test skill\n---\n",
        encoding="utf-8",
    )
    return create_sandbox._create_sandbox(source, tmp_path)


def test_sanitize_command_rewrites_python_launcher():
    argv = run_smoke._sanitize_command("python3 scripts/tool.py --help")
    assert argv == [sys.executable, "scripts/tool.py", "--help"]

    argv = run_smoke._sanitize_command("python scripts/tool.py -q")
    assert argv == [sys.executable, "scripts/tool.py", "-q"]

    argv = run_smoke._sanitize_command("/usr/bin/env python3 -V")
    assert argv == ["/usr/bin/env", "python3", "-V"]


def test_sanitize_command_rejects_invalid_input():
    bad_commands = [
        "",
        "   ",
        "python3 bad.py\x00",
        "'unterminated",
    ]
    for command in bad_commands:
        with pytest.raises(ValueError):
            run_smoke._sanitize_command(command)

    with pytest.raises(ValueError):
        run_smoke._sanitize_command(None)


def test_main_runs_command_with_sandbox_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sandbox = _make_sandbox(tmp_path)
    script = sandbox / "write_cwd.py"
    output = sandbox / "cwd.txt"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path(sys.argv[1]).write_text(str(Path.cwd()))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_smoke.py",
            "--sandbox-dir",
            str(sandbox),
            "--command",
            f"python3 {script.name} {output.name}",
        ],
    )

    assert run_smoke.main() == 0
    assert output.read_text(encoding="utf-8") == str(sandbox.resolve())


def test_smoke_environment_is_allowlisted_and_sandbox_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = _make_sandbox(tmp_path)
    output = sandbox / "environment.json"
    script = sandbox / "inspect_environment.py"
    script.write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "keys = ['HOME', 'TMPDIR', 'TMP', 'TEMP', 'PYTHONPATH', 'LOCALSETUP_TEST_SECRET']\n"
        "Path('environment.json').write_text(json.dumps({key: os.environ.get(key) for key in keys}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCALSETUP_TEST_SECRET", "must-not-leak")
    monkeypatch.setenv("PYTHONPATH", "/host/framework/lib")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_smoke.py",
            "--sandbox-dir",
            str(sandbox),
            "--command",
            "python3 inspect_environment.py",
        ],
    )

    assert run_smoke.main() == 0

    environment = json.loads(output.read_text(encoding="utf-8"))
    runtime_root = sandbox / ".localsetup-runtime"
    assert environment["HOME"] == str(runtime_root / "home")
    assert environment["TMPDIR"] == str(runtime_root / "tmp")
    assert environment["TMP"] == str(runtime_root / "tmp")
    assert environment["TEMP"] == str(runtime_root / "tmp")
    assert environment["PYTHONPATH"] is None
    assert environment["LOCALSETUP_TEST_SECRET"] is None


def test_rejects_arbitrary_directory_without_provenance(tmp_path: Path) -> None:
    arbitrary = tmp_path / "arbitrary"
    arbitrary.mkdir()

    with pytest.raises(ValueError, match="provenance marker"):
        run_smoke._sanitize_path(str(arbitrary))


def test_rejects_tampered_marker(tmp_path: Path) -> None:
    sandbox = _make_sandbox(tmp_path)
    marker = sandbox.parent / run_smoke.MARKER_NAME
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["sandbox_dir"] = str(tmp_path / "other")
    marker.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match provenance"):
        run_smoke._sanitize_path(str(sandbox))


def test_rejects_symlink_added_to_sandbox(tmp_path: Path) -> None:
    sandbox = _make_sandbox(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (sandbox / "escape.txt").symlink_to(outside)

    with pytest.raises(ValueError, match="contains a symlink"):
        run_smoke._sanitize_path(str(sandbox))


@pytest.mark.parametrize("tamper", ["content", "symlink", "parent-symlink", "missing", "declaration", "path", "hash", "extra-file"])
def test_shared_deps_tampering_prevents_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    source = tmp_path / "source" / "ls-example"
    source.mkdir(parents=True)
    dependency = tmp_path / "deps.py"
    dependency.write_text("VALUE = 1\n", encoding="utf-8")
    sandbox = create_sandbox._create_sandbox(source, tmp_path, dependency)
    staged = sandbox.parent / run_smoke.SHARED_DEPS_PATH
    marker = sandbox.parent / run_smoke.MARKER_NAME
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if tamper == "content":
        staged.write_text("VALUE = 2\n", encoding="utf-8")
    elif tamper == "symlink":
        staged.unlink()
        staged.symlink_to(dependency)
    elif tamper == "parent-symlink":
        staged.unlink()
        staged.parent.rmdir()
        staged.parent.symlink_to(tmp_path, target_is_directory=True)
    elif tamper == "missing":
        staged.unlink()
    elif tamper == "extra-file":
        (staged.parent / "ambient_only.py").write_text("", encoding="utf-8")
    elif tamper == "declaration":
        payload["shared_deps"] = None
    elif tamper == "path":
        payload["shared_deps"]["path"] = str(dependency)
    else:
        payload["shared_deps"]["sha256"] = "invalid"
    marker.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["run_smoke.py", "--sandbox-dir", str(sandbox), "--command", "python3 -V"])
    monkeypatch.setattr(run_smoke.subprocess, "run", lambda *args, **kwargs: pytest.fail("command executed"))
    assert run_smoke.main() == 2
