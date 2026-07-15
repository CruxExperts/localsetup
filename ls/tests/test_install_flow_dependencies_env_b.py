from __future__ import annotations

from ls.tests.test_install_flow import *

def test_uv_sync_quarantines_corrupt_source_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    broken_python = root / ".venv" / "bin" / "python"
    broken_python.parent.mkdir(parents=True)
    broken_python.write_text("# fake python\n", encoding="utf-8")
    broken_python.chmod(0o644)
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        if "sync" in cmd:
            python_path = root / ".venv" / "bin" / "python"
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("# rebuilt python\n", encoding="utf-8")
            python_path.chmod(0o755)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    deps = ensure_dependencies(root, mode="uv-sync", runner=fake_runner)

    quarantined = deps["quarantined_environments"]
    assert deps["repair_attempted"] is True
    assert len(quarantined) == 1
    assert quarantined[0]["owner"] == "source_venv"
    assert Path(quarantined[0]["quarantine_path"]).is_dir()
    assert Path(quarantined[0]["record_path"]).is_file()
    assert broken_python.read_text(encoding="utf-8") == "# rebuilt python\n"
    assert deps["sync_attempts"] == 1


def test_uv_sync_retries_source_venv_corruption_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    python_path = root / ".venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("# healthy before uv failure\n", encoding="utf-8")
    python_path.chmod(0o755)
    (root / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")
    sync_calls = 0

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal sync_calls
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        if "sync" in cmd:
            sync_calls += 1
            if sync_calls == 1:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="failed to read .venv/pyvenv.cfg")
            rebuilt = root / ".venv" / "bin" / "python"
            rebuilt.parent.mkdir(parents=True, exist_ok=True)
            rebuilt.write_text("# rebuilt after retry\n", encoding="utf-8")
            rebuilt.chmod(0o755)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    deps = ensure_dependencies(root, mode="uv-sync", runner=fake_runner)

    assert deps["sync_attempts"] == 2
    assert sync_calls == 2
    assert deps["quarantined_environments"][0]["uv_error"] == "failed to read .venv/pyvenv.cfg"
    assert python_path.read_text(encoding="utf-8") == "# rebuilt after retry\n"


def test_uv_sync_repairs_legacy_envs_without_touching_target_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "project"
    data_root = home / ".local" / "share" / "localsetup"
    legacy_global = data_root / "venv" / "bin" / "python"
    legacy_target = target / ".localsetup" / "venv" / "bin" / "python"
    project_python = target / ".venv" / "bin" / "python"
    for path in (legacy_global, legacy_target, project_python):
        path.parent.mkdir(parents=True)
        path.write_text("# fake python\n", encoding="utf-8")
        path.chmod(0o644)
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        if "sync" in cmd:
            rebuilt = root / ".venv" / "bin" / "python"
            rebuilt.parent.mkdir(parents=True, exist_ok=True)
            rebuilt.write_text("# rebuilt python\n", encoding="utf-8")
            rebuilt.chmod(0o755)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    deps = ensure_dependencies(root, mode="uv-sync", data_root=data_root, target_root=target, runner=fake_runner)

    owners = {item["owner"] for item in deps["quarantined_environments"]}
    assert owners == {"legacy_global_venv", "legacy_target_local_venv"}
    assert not (data_root / "venv").exists()
    assert not (target / ".localsetup" / "venv").exists()
    assert project_python.exists()
    assert project_python.read_text(encoding="utf-8") == "# fake python\n"


def test_uv_sync_leaves_healthy_source_venv_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    python_path = root / ".venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("# healthy python\n", encoding="utf-8")
    python_path.chmod(0o755)
    (root / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    deps = ensure_dependencies(root, mode="uv-sync", runner=fake_runner)

    assert deps["repair_attempted"] is False
    assert deps["quarantined_environments"] == []
    assert python_path.read_text(encoding="utf-8") == "# healthy python\n"


def test_uv_sync_quarantine_failure_blocks_without_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ls.core import dependencies as deps_mod

    root = make_temp_repo(tmp_path)
    broken_python = root / ".venv" / "bin" / "python"
    broken_python.parent.mkdir(parents=True)
    broken_python.write_text("# fake python\n", encoding="utf-8")
    broken_python.chmod(0o644)
    original_rename = Path.rename

    def failing_rename(self: Path, target: Path) -> Path:
        if self == root / ".venv":
            raise OSError("simulated rename failure")
        return original_rename(self, target)

    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")
    monkeypatch.setattr(deps_mod.Path, "rename", failing_rename)

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    with pytest.raises(RuntimeError, match="failed to quarantine Localsetup-owned environment"):
        ensure_dependencies(root, mode="uv-sync", runner=fake_runner)
    assert broken_python.exists()


def test_uv_sync_failure_preserves_quarantine_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    broken_python = root / ".venv" / "bin" / "python"
    broken_python.parent.mkdir(parents=True)
    broken_python.write_text("# fake python\n", encoding="utf-8")
    broken_python.chmod(0o644)
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        if "sync" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="offline cache miss")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    with pytest.raises(RuntimeError, match="offline-cache-miss"):
        ensure_dependencies(root, mode="uv-sync", runner=fake_runner)
    assert list((root / ".localsetup" / "state" / "dependency-repair").glob(".venv-*.json"))


def test_uv_stale_lock_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_temp_repo(tmp_path)
    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    def fake_runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="uv 0.11.5\n", stderr="")
        if cmd[-2:] == ["lock", "--check"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="lock would change")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with pytest.raises(RuntimeError, match="uv lockfile is stale"):
        ensure_dependencies(root, mode="uv-sync", runner=fake_runner)
