import importlib.util
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "ls" / "skills" / "ls-kilo-boss-orchestrator" / "scripts"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))
for module_name in list(sys.modules):
    if module_name == "lib" or module_name.startswith("lib."):
        sys.modules.pop(module_name, None)


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_module("ls_kilo_headless_runner", SKILL_ROOT / "kilo_headless_runner.py")
boss_ctl = _load_module("ls_kilo_boss_ctl", SKILL_ROOT / "boss_ctl.py")
STORE_CLASS = runner.StateStore


def _configure_tmp_state(monkeypatch, tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(runner, "ROUTER_SCRIPT", tmp_path / "missing_router.py")
    monkeypatch.setattr(
        runner,
        "StateStore",
        lambda: STORE_CLASS(root=state_root),
    )


def _write_task(monkeypatch, tmp_path: Path, task_payload: dict, session_payload: dict | None = None) -> None:
    _configure_tmp_state(monkeypatch, tmp_path)
    store = STORE_CLASS(root=tmp_path / "state")
    store.write_task(task_payload)
    if session_payload is not None:
        store.write_session(task_payload["session_id"], session_payload)


def _install_fake_kilo(monkeypatch, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    kilo = bin_dir / "kilo"
    kilo.write_text(
        """#!/usr/bin/env python3
import sys
import time

if len(sys.argv) < 3 or sys.argv[1] != "run":
    print("expected kilo run <mode>", file=sys.stderr)
    raise SystemExit(64)

mode = sys.argv[2]
if mode == "sleep":
    time.sleep(2)
elif mode == "fail":
    print("boom", file=sys.stderr)
    raise SystemExit(7)
elif mode == "echo-arg":
    print(sys.argv[-1])
else:
    print("ok")
""",
        encoding="utf-8",
    )
    kilo.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


def test_rejects_free_form_string_command() -> None:
    argv, error = runner._normalize_command("echo ok && echo bad")
    assert argv == []
    assert error is not None
    assert "command_argv YAML list" in error


def test_accepts_literal_shell_like_argv_argument() -> None:
    argv, error = runner._normalize_command(["kilo", "run", "echo-arg", "a&&b;still-literal"])
    assert error is None
    assert argv[-1] == "a&&b;still-literal"


def test_run_worker_timeout_records_timed_out_result(monkeypatch, tmp_path: Path) -> None:
    _install_fake_kilo(monkeypatch, tmp_path)
    task_id = "task-timeout"
    session_id = "session-timeout"
    _write_task(
        monkeypatch,
        tmp_path,
        {
            "id": task_id,
            "session_id": session_id,
            "command": ["kilo", "run", "sleep"],
            "timeout_seconds": 1,
            "repo_root": str(ROOT),
        },
        {"session_shared": True, "session_visibility": "shared-authenticated"},
    )

    rc = runner.run_worker(task_id, "worker-timeout", session_id)

    assert rc == 124
    store = STORE_CLASS(root=tmp_path / "state")
    result = store.read_result(task_id)
    assert result is not None
    assert result["status"] == "timed_out"
    assert result["exit_code"] == 124
    assert "timed out after 1s" in result["stderr"]


def test_run_worker_failure_surfaces_exit_code_and_stderr(monkeypatch, tmp_path: Path) -> None:
    _install_fake_kilo(monkeypatch, tmp_path)
    task_id = "task-fail"
    session_id = "session-fail"
    _write_task(
        monkeypatch,
        tmp_path,
        {
            "id": task_id,
            "session_id": session_id,
            "command": ["kilo", "run", "fail"],
            "timeout_seconds": 10,
            "repo_root": str(ROOT),
        },
        {"session_shared": True, "session_visibility": "shared-authenticated"},
    )

    rc = runner.run_worker(task_id, "worker-fail", session_id)

    assert rc == 2
    store = STORE_CLASS(root=tmp_path / "state")
    result = store.read_result(task_id)
    assert result is not None
    assert result["status"] == "failed"
    assert result["exit_code"] == 7
    assert "boom" in result["stderr"]


def test_run_worker_executes_safe_argv_without_shell(monkeypatch, tmp_path: Path) -> None:
    _install_fake_kilo(monkeypatch, tmp_path)
    task_id = "task-ok"
    session_id = "session-ok"
    _write_task(
        monkeypatch,
        tmp_path,
        {
            "id": task_id,
            "session_id": session_id,
            "command": ["kilo", "run", "echo-arg", "a&&b"],
            "timeout_seconds": 10,
            "repo_root": str(ROOT),
        },
        {"session_shared": True, "session_visibility": "shared-authenticated"},
    )

    rc = runner.run_worker(task_id, "worker-ok", session_id)

    assert rc == 0
    store = STORE_CLASS(root=tmp_path / "state")
    result = store.read_result(task_id)
    assert result is not None
    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert "a&&b" in result["stdout"]


def test_spawn_worker_task_raises_actionable_error(monkeypatch) -> None:
    def _raise_oserror(*args, **kwargs):
        raise OSError("spawn blocked")

    monkeypatch.setattr("subprocess.run", _raise_oserror)

    try:
        boss_ctl._spawn_worker_task("task-1", "worker-1", "session-1")
    except RuntimeError as exc:
        text = str(exc)
        assert "failed to spawn worker task 'task-1'" in text
        assert "spawn blocked" in text
    else:
        raise AssertionError("expected RuntimeError")


def test_spawn_worker_task_raises_on_nonzero_child(monkeypatch) -> None:
    class Result:
        returncode = 9
        stdout = "runner stdout"
        stderr = "runner stderr"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())

    try:
        boss_ctl._spawn_worker_task("task-2", "worker-2", "session-2")
    except RuntimeError as exc:
        text = str(exc)
        assert "worker task 'task-2' exited 9" in text
        assert "runner stderr" in text
    else:
        raise AssertionError("expected RuntimeError")
