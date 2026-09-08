"""Candidate worker bytes must match Git, with unchanged published SDK locks."""
import subprocess
import zipfile

import pytest

from ls.core.release_docs import runtime_candidate as candidate


@pytest.mark.parametrize("mutation", [None, "code", "dependency", "untracked", "shell", "sdk"])
def test_candidate_wheel_binding(tmp_path, monkeypatch, mutation):
    root = tmp_path / "repo"
    root.mkdir()
    member = "ls/core/agent/provider_client.py"
    source = root / member
    source.parent.mkdir(parents=True)
    source.write_text("# candidate transport\n")
    for name in ("sdk-build.lock", "sdk-runtime.lock"):
        path = root / "ls/config" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("locked")
    for args in [("init",), ("add", "."), ("-c", "user.name=Fixture", "-c",
                  "user.email=fixture@example.invalid", "commit", "-qm", "fixture")]:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    assets = tmp_path / "assets"
    assets.mkdir()
    baseline = assets / "baseline.whl"
    with zipfile.ZipFile(baseline, "w") as archive:
        archive.writestr("ls/_sdk_payload/manifest.json", "sdk-fixture")
        for name in ("sdk-build.lock", "sdk-runtime.lock"):
            archive.writestr("ls/config/" + name, "locked")
    original_run = subprocess.run

    def run(command, **kwargs):
        if command[0] != "uv":
            return original_run(command, **kwargs)
        assert "--offline" in command and "--no-build-isolation" in command
        assert "--config-settings=--global-option=build" in command
        assert "--config-settings=--global-option=--build-base=" + str(assets / "build") in command
        assert command[command.index("--python") + 1] == "/locked/python"
        with zipfile.ZipFile(assets / "candidate-wheel/candidate.whl", "w") as archive:
            archive.writestr("ls/_sdk_payload/manifest.json", "changed" if mutation == "sdk" else "sdk-fixture")
            for name in ("sdk-build.lock", "sdk-runtime.lock"):
                archive.writestr("ls/config/" + name, "changed" if mutation == "dependency" else "locked")
            archive.writestr(member, "changed" if mutation == "code" else source.read_bytes())
            if mutation == "untracked":
                archive.writestr("ls/injected.py", "# not in source commit")
            if mutation == "shell":
                archive.writestr("ls/skills/example/injected.sh", "echo injected")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(candidate.subprocess, "run", run)
    monkeypatch.setattr(candidate, "inspect_artifact", lambda path: {})
    if mutation:
        with pytest.raises(ValueError, match="differs|differ|untracked"):
            candidate.build_candidate(root, assets, baseline, "/locked/python", {})
        assert not (assets / "candidate-runtime.json").exists()
    else:
        result = candidate.build_candidate(root, assets, baseline, "/locked/python", {})
        assert result["verified_source_members"] == 3
        assert result["source_commit"] == candidate.git(root, "rev-parse", "HEAD")
        assert (assets / "candidate-runtime.json").exists()


def test_dirty_source_refused_before_build(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate, "git", lambda root, *args: "a" * 40 if args[0] == "rev-parse" else " M source.py")
    with pytest.raises(ValueError, match="clean source"):
        candidate.build_candidate(tmp_path, tmp_path, tmp_path / "unused", "/unused", {})
    assert not (tmp_path / "candidate-wheel").exists()
