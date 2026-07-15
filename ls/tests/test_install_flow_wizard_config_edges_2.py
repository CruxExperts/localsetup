from __future__ import annotations

from ls.tests.test_install_flow import *

def test_dependency_status_and_ensure_error_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ls.core import dependencies as deps

    root = make_temp_repo(tmp_path)

    monkeypatch.delenv("LOCALSETUP_UV_BIN", raising=False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)
    status = deps.dependency_status(root)
    assert status.mode == "prompt-only"
    assert status.ok is False
    assert any("uv is required" in blocker for blocker in status.blockers)

    monkeypatch.setenv("LOCALSETUP_UV_BIN", "uv")

    old_uv_commands: list[list[str]] = []

    def old_uv_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        old_uv_commands.append(cmd)
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, "uv 0.4.26\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    old_status = deps.dependency_status(root, runner=old_uv_runner)
    assert old_status.ok is False
    assert old_status.minimum_version == "0.4.27"
    assert any("uv 0.4.26 is too old" in blocker for blocker in old_status.blockers)
    assert old_status.lock_status == "unchecked"
    assert not any(cmd[-2:] == ["lock", "--check"] for cmd in old_uv_commands)

    missing_lock_root = make_temp_repo(tmp_path / "missing-lock")
    (missing_lock_root / "uv.lock").unlink()
    missing_status = deps.dependency_status(missing_lock_root, runner=old_uv_runner)
    assert missing_status.lock_status == "missing"
    assert any("uv.lock not found" in blocker for blocker in missing_status.blockers)

    def stale_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, "uv 0.11.5\n", "")
        if cmd[-2:] == ["lock", "--check"]:
            return subprocess.CompletedProcess(cmd, 1, "", "lock would change")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    stale_status = deps.dependency_status(root, runner=stale_runner)
    assert stale_status.lock_status == "stale"
    with pytest.raises(RuntimeError, match="uv lockfile is stale"):
        deps.ensure_dependencies(root, mode="uv-sync", runner=stale_runner)

    def fail_sync_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[-1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, "uv 0.11.5\n", "")
        if "sync" in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "network timed out")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with pytest.raises(RuntimeError, match="network-or-index"):
        deps.ensure_dependencies(root, mode="uv-sync", runner=fail_sync_runner)

    prompt = deps.ensure_dependencies(root, mode="user-pip", runner=fail_sync_runner)
    assert prompt["mode"] == "prompt-only"
    assert prompt["changed"] is False
