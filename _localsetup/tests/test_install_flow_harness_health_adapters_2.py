from __future__ import annotations

from _localsetup.tests.test_install_flow import *

def test_health_cli_written_after_install(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"

    status = cli_mod._main(["--source-root", str(root), "--home", str(home), "install", "--yes", "--packs", "core"])
    assert status == 0
    capsys.readouterr()

    health = load_json(root / ".localsetup" / "health.json")
    assert health["status"] == "ok"
    assert health["operation"] == "install"
    assert (root / ".localsetup" / "AGENT_STATUS.md").is_file()

    assert cli_mod._main(["--source-root", str(root), "--home", str(home), "health", "repair-queue", "--json"]) == 0
    queue = json.loads(capsys.readouterr().out)
    assert queue["ok"] is True


def test_package_root_lock_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from _localsetup.core.locking import PackageRootLockTimeout, package_root_lock

    home = tmp_path / "home" / ".local" / "share" / "localsetup"
    ready = tmp_path / "ready"
    script = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from _localsetup.core.locking import package_root_lock\n"
        "home = Path(sys.argv[1])\n"
        "ready = Path(sys.argv[2])\n"
        "with package_root_lock(home, timeout=1):\n"
        "    ready.write_text('ready', encoding='utf-8')\n"
        "    time.sleep(2)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", script, str(home), str(ready)])
    try:
        deadline = time.time() + 5
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        monkeypatch.setenv("LOCALSETUP_PACKAGE_ROOT_LOCK_TIMEOUT", "0.1")
        with pytest.raises(PackageRootLockTimeout):
            with package_root_lock(home):
                pass
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_health_uses_global_shim_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from _localsetup.core.health import write_health_event

    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target"
    target.mkdir()
    write_health_event(
        repo_root=root,
        home=home,
        target_root=target,
        operation="doctor",
        mode="report-only",
        status="ok",
        payload={},
    )
    monkeypatch.setenv(cli_mod.SHIM_ENV, "1")
    monkeypatch.setattr(cli_mod, "detect_invocation_target", lambda: target)

    status = cli_mod._main(["--source-root", str(root), "--home", str(home), "health", "--json"])
    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["event"]["target_root"] == str(target.resolve())
