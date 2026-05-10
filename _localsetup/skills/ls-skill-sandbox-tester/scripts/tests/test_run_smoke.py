from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_smoke.py"


def _load_run_smoke_module():
    spec = importlib.util.spec_from_file_location("run_smoke", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_smoke = _load_run_smoke_module()


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
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

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

    rc = run_smoke.main()

    assert rc == 0
    assert output.exists()
    assert output.read_text(encoding="utf-8") == str(sandbox.resolve())
