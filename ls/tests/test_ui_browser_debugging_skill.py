from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "ls" / "skills" / "ls-ui-browser-debugging"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def env_module():
    return load_module("chrome_devtools_mcp_environment_under_test", SKILL / "scripts" / "chrome_devtools_mcp_environment.py")


def verifier_module():
    return load_module("verify_ui_browser_debugging_sources_under_test", SKILL / "scripts" / "verify_ui_browser_debugging_sources.py")


def guard_module():
    return load_module("browser_session_guard_under_test", SKILL / "scripts" / "browser_session_guard.py")


def test_ui_browser_debugging_skill_is_registered() -> None:
    skill_md = SKILL / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert frontmatter["name"] == "ls-ui-browser-debugging"
    assert "UI review and browser-driven debugging workflow" in frontmatter["description"]
    assert frontmatter["metadata"]["version"] == "1.0"

    pack = yaml.safe_load((ROOT / "ls" / "config" / "pack.yaml").read_text(encoding="utf-8"))
    assert "ls-ui-browser-debugging" in pack["packs"]["dev"]
    assert pack["extensions"]["skill_taxonomy"]["ls-ui-browser-debugging"] == {
        "class": "development",
        "sort_priority": 30,
        "tags": ["ui", "browser", "debugging", "mcp"],
        "owner_scope": "skill",
    }

    smoke = yaml.safe_load((ROOT / "ls" / "tests" / "skill_smoke_commands.yaml").read_text(encoding="utf-8"))
    assert smoke["ls-ui-browser-debugging"] == "python3 scripts/verify_ui_browser_debugging_sources.py --help"


def test_ui_browser_debugging_required_files_exist() -> None:
    required = [
        "references/source-ledger.md",
        "references/mcp-bootstrap-and-repair.md",
        "references/browser-session-management.md",
        "references/ui-feasibility-review.md",
        "references/subagent-browser-workflows.md",
        "references/browser-mcp-landscape.md",
        "scripts/browser_session_guard.py",
        "scripts/chrome_devtools_mcp_environment.py",
        "scripts/verify_ui_browser_debugging_sources.py",
    ]
    missing = [path for path in required if not (SKILL / path).is_file()]
    assert missing == []


def test_environment_inspect_warns_without_host_tools(monkeypatch) -> None:
    module = env_module()
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    payload, code = module.inspect(require=False)

    assert code == 0
    assert payload["status"] == "ok"
    assert payload["commands"]["node"]["available"] is False
    assert payload["commands"]["npx"]["available"] is False
    assert payload["chrome"]["available"] is False
    assert len(payload["warnings"]) == 3


def test_environment_inspect_require_fails_without_host_tools(monkeypatch) -> None:
    module = env_module()
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    payload, code = module.inspect(require=True)

    assert code == 1
    assert payload["status"] == "missing_requirements"
    assert {error.split(" is required", 1)[0] for error in payload["errors"]} == {"node", "npx", "Chrome/Chromium"}


def test_environment_linux_chrome_path_discovery(monkeypatch) -> None:
    module = env_module()

    def fake_which(name: str) -> str | None:
        if name == "google-chrome":
            return "/usr/bin/google-chrome"
        return None

    monkeypatch.setattr(module.shutil, "which", fake_which)
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    chrome = module.chrome_fact()

    assert chrome["available"] is True
    assert chrome["paths"] == ["/usr/bin/google-chrome"]
    assert "google-chrome" in chrome["checked"]


def test_environment_standard_config_defaults_to_isolated_mode() -> None:
    module = env_module()
    config = module.standard_config()

    assert config["command"] == "npx"
    assert config["mode"] == "isolated"
    assert config["args"][:2] == ["-y", "chrome-devtools-mcp@latest"]
    assert "--no-usage-statistics" in config["args"]
    assert "--no-performance-crux" in config["args"]
    assert "--redactNetworkHeaders" in config["args"]
    assert "--isolated=true" in config["args"]
    assert not any(arg.startswith("--userDataDir=") for arg in config["args"])
    assert config["recommended_profile_dir"] is None
    assert config["pinned_reproducibility_snapshot"]["version"] == "1.4.0"


def test_environment_standard_config_supports_explicit_persistent_mode() -> None:
    module = env_module()
    config = module.standard_config("persistent")

    assert config["mode"] == "persistent"
    assert "--isolated=true" not in config["args"]
    assert "--userDataDir=.localsetup-maint/ui-browser-profiles/chrome-devtools" in config["args"]
    assert config["recommended_profile_dir"] == ".localsetup-maint/ui-browser-profiles/chrome-devtools"


def test_environment_repo_root_is_checkout_root() -> None:
    module = env_module()
    assert module.repo_root() == ROOT


def test_environment_examples_are_source_backed_or_documentation_required() -> None:
    module = env_module()
    codex = module.example("codex")
    cursor = module.example("cursor")
    kilo = module.example("kilo")
    opencode = module.example("opencode")
    claude = module.example("claude-code")
    openclaw = module.example("openclaw")
    unknown = module.example("unknown")

    assert codex["status"] == "source_backed"
    assert "[mcp_servers.chrome-devtools]" in codex["example"]["snippet"]
    assert "chrome-devtools-mcp@latest" in codex["example"]["snippet"]
    assert "--isolated=true" in codex["example"]["snippet"]
    assert cursor["status"] == "source_backed"
    assert '"mcpServers"' in cursor["example"]["snippet"]
    assert kilo["status"] == "source_backed"
    assert '"type": "local"' in kilo["example"]["snippet"]
    assert opencode["status"] == "source_backed"
    assert '"$schema": "https://opencode.ai/config.json"' in opencode["example"]["snippet"]
    assert claude["status"] == "documentation_required"
    assert openclaw["status"] == "documentation_required"
    assert unknown["status"] == "unsupported_agent"


def test_environment_cli_outputs_json() -> None:
    result = subprocess.run(
        ["python3", "scripts/chrome_devtools_mcp_environment.py", "standard-config", "--json"],
        cwd=SKILL,
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["mcp_server"]["name"] == "chrome-devtools"
    assert payload["mcp_server"]["mode"] == "isolated"
    assert "--isolated=true" in payload["mcp_server"]["args"]


def test_environment_cli_supports_persistent_mode() -> None:
    result = subprocess.run(
        ["python3", "scripts/chrome_devtools_mcp_environment.py", "standard-config", "--mode", "persistent", "--json"],
        cwd=SKILL,
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["mcp_server"]["mode"] == "persistent"
    assert "--userDataDir=.localsetup-maint/ui-browser-profiles/chrome-devtools" in payload["mcp_server"]["args"]


def test_environment_cli_non_json_output_is_human_readable() -> None:
    result = subprocess.run(
        ["python3", "scripts/chrome_devtools_mcp_environment.py", "standard-config"],
        cwd=SKILL,
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.startswith("ok: ok\n")
    assert "{\n" not in result.stdout
    assert "chrome-devtools-mcp@latest" in result.stdout
    assert "--isolated=true" in result.stdout


def test_browser_session_guard_start_records_isolated_session(monkeypatch, tmp_path) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)

    payload = module.start_session("chrome-devtools", "isolated", "controller", "ui debug", "session-1")

    assert payload["schema_version"] == 2
    assert payload["status"] == "active"
    assert payload["mode"] == "isolated"
    assert payload["profile_dir"] is None
    assert payload["pages"] == []
    record_path = tmp_path / ".localsetup-maint" / "ui-browser-sessions" / "session-1.json"
    assert record_path.is_file()


def test_browser_session_guard_record_select_and_finish_requires_cleanup(monkeypatch, tmp_path) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)

    module.start_session("chrome-devtools", "isolated", "controller", "ui debug", "session-2")
    recorded = module.record_page("session-2", "page-1", "http://localhost:3000", "inspect route")
    selected = module.select_page("session-2", "page-1")
    payload, code = module.finish_session("session-2")

    assert recorded["active_page_id"] == "page-1"
    assert selected["active_page_id"] == "page-1"
    assert code == 1
    assert payload["status"] == "needs_cleanup"
    assert payload["cleanup_actions"][0]["action"] == "close_page"
    assert payload["cleanup_actions"][0]["page_id"] == "page-1"


def test_browser_session_guard_mark_closed_then_finish_succeeds(monkeypatch, tmp_path) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)

    module.start_session("chrome-devtools", "isolated", "controller", "ui debug", "session-3")
    module.record_page("session-3", "page-1", "http://localhost:3000", "inspect route")
    closed = module.mark_closed("session-3", "page-1")
    payload, code = module.finish_session("session-3")

    assert closed["pages"][0]["status"] == "closed"
    assert code == 0
    assert payload["status"] == "finished"
    assert payload["cleanup_actions"] == []


def test_browser_session_guard_legacy_may_close_false_is_not_owned(monkeypatch, tmp_path) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    record_dir = tmp_path / ".localsetup-maint" / "ui-browser-sessions"
    record_dir.mkdir(parents=True)
    (record_dir / "readonly.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "session_id": "readonly",
                "controller": "controller",
                "mcp_server": "chrome-devtools",
                "profile_dir": ".localsetup-maint/ui-browser-profiles/chrome-devtools",
                "routing": "selected-page",
                "pages": [
                    {
                        "pageId": "user-page",
                        "url": "http://localhost:3000",
                        "purpose": "pre-existing page",
                        "may_close": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    audited = module.audit_session("readonly")
    payload, code = module.finish_session("readonly")

    assert audited["pages"][0]["owned"] is False
    assert audited["cleanup_actions"] == []
    assert code == 0
    assert payload["status"] == "finished"


def test_browser_session_guard_missing_ownership_defaults_to_unowned(monkeypatch, tmp_path) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    record_dir = tmp_path / ".localsetup-maint" / "ui-browser-sessions"
    record_dir.mkdir(parents=True)
    (record_dir / "missing-owner.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "session_id": "missing-owner",
                "status": "active",
                "mode": "persistent",
                "tool": "chrome-devtools",
                "owner": "controller",
                "purpose": "audit",
                "profile_dir": ".localsetup-maint/ui-browser-profiles/chrome-devtools",
                "pages": [
                    {
                        "page_id": "page-1",
                        "url": "http://localhost:3000",
                        "purpose": "unknown owner",
                        "status": "open",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    audited = module.audit_session("missing-owner")

    assert audited["pages"][0]["owned"] is False
    assert audited["cleanup_actions"] == []


def test_browser_session_guard_rejects_malformed_boolean_ownership(monkeypatch, tmp_path) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    record_dir = tmp_path / ".localsetup-maint" / "ui-browser-sessions"
    record_dir.mkdir(parents=True)
    (record_dir / "bad-owner.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "session_id": "bad-owner",
                "status": "active",
                "mode": "persistent",
                "tool": "chrome-devtools",
                "owner": "controller",
                "purpose": "audit",
                "profile_dir": ".localsetup-maint/ui-browser-profiles/chrome-devtools",
                "pages": [
                    {
                        "page_id": "page-1",
                        "url": "http://localhost:3000",
                        "purpose": "bad owner",
                        "owned": "false",
                        "status": "open",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.SessionGuardError):
        module.audit_session("bad-owner")


def test_browser_session_guard_select_page_rejects_unowned_records(monkeypatch, tmp_path) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    record_dir = tmp_path / ".localsetup-maint" / "ui-browser-sessions"
    record_dir.mkdir(parents=True)
    (record_dir / "unowned.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "session_id": "unowned",
                "status": "active",
                "mode": "persistent",
                "tool": "chrome-devtools",
                "owner": "controller",
                "purpose": "audit",
                "profile_dir": ".localsetup-maint/ui-browser-profiles/chrome-devtools",
                "pages": [
                    {
                        "page_id": "page-1",
                        "url": "http://localhost:3000",
                        "purpose": "user page",
                        "owned": False,
                        "may_close": False,
                        "status": "open",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.SessionGuardError):
        module.select_page("unowned", "page-1")


def test_browser_session_guard_rejects_unsafe_session_id(monkeypatch, tmp_path) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)

    with pytest.raises(module.SessionGuardError):
        module.start_session("chrome-devtools", "isolated", "controller", "ui debug", "../bad")


def test_browser_session_guard_rejects_unsafe_page_id(monkeypatch, tmp_path) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)

    module.start_session("chrome-devtools", "isolated", "controller", "ui debug", "session-4")
    with pytest.raises(module.SessionGuardError):
        module.record_page("session-4", "../bad", "http://localhost:3000", "inspect route")


def test_browser_session_guard_rejects_unsafe_profile_dir(monkeypatch, tmp_path) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    record_dir = tmp_path / ".localsetup-maint" / "ui-browser-sessions"
    record_dir.mkdir(parents=True)
    (record_dir / "bad-profile.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "session_id": "bad-profile",
                "status": "active",
                "mode": "persistent",
                "tool": "chrome-devtools",
                "owner": "controller",
                "purpose": "audit",
                "profile_dir": "../../.config/google-chrome/Default",
                "pages": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.SessionGuardError):
        module.audit_session("bad-profile")


def test_browser_session_guard_reads_and_upgrades_v1_records(monkeypatch, tmp_path) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    record_dir = tmp_path / ".localsetup-maint" / "ui-browser-sessions"
    record_dir.mkdir(parents=True)
    (record_dir / "legacy.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "session_id": "legacy",
                "controller": "controller",
                "mcp_server": "chrome-devtools",
                "profile_dir": ".localsetup-maint/ui-browser-profiles/chrome-devtools",
                "routing": "selected-page",
                "active_page_id": 7,
                "pages": [
                    {
                        "pageId": 7,
                        "url": "http://localhost:3000",
                        "purpose": "legacy debug",
                        "may_close": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    audited = module.audit_session("legacy")
    finished, code = module.finish_session("legacy")

    assert audited["schema_version"] == 2
    assert audited["owner"] == "controller"
    assert audited["tool"] == "chrome-devtools"
    assert audited["pages"][0]["page_id"] == "7"
    assert audited["cleanup_actions"][0]["action"] == "close_page"
    assert code == 1
    assert finished["status"] == "needs_cleanup"


def test_browser_session_guard_reads_v1_isolated_profile_records(monkeypatch, tmp_path) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    record_dir = tmp_path / ".localsetup-maint" / "ui-browser-sessions"
    record_dir.mkdir(parents=True)
    (record_dir / "legacy-isolated.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "session_id": "legacy-isolated",
                "controller": "controller",
                "mcp_server": "chrome-devtools",
                "profile_dir": ".localsetup-maint/ui-browser-profiles/subagent-a",
                "routing": "isolated-profile",
                "active_page_id": "page-1",
                "pages": [
                    {
                        "pageId": "page-1",
                        "url": "http://localhost:3000",
                        "purpose": "legacy isolated profile",
                        "may_close": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    audited = module.audit_session("legacy-isolated")
    finished, code = module.finish_session("legacy-isolated")

    assert audited["schema_version"] == 2
    assert audited["mode"] == "persistent"
    assert audited["profile_dir"] == ".localsetup-maint/ui-browser-profiles/subagent-a"
    assert audited["pages"][0]["owned"] is True
    assert audited["cleanup_actions"][0]["action"] == "close_page"
    assert code == 1
    assert finished["status"] == "needs_cleanup"


def test_browser_session_guard_main_finish_returns_one_when_cleanup_remains(monkeypatch, tmp_path, capsys) -> None:
    module = guard_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)

    module.start_session("chrome-devtools", "isolated", "controller", "ui debug", "session-5")
    module.record_page("session-5", "page-1", "http://localhost:3000", "inspect route")
    code = module.main(["finish", "--session-id", "session-5", "--json"])
    output = json.loads(capsys.readouterr().out)

    assert code == 1
    assert output["status"] == "needs_cleanup"
    assert output["cleanup_actions"][0]["action"] == "close_page"


def test_browser_session_guard_help_exits_cleanly() -> None:
    result = subprocess.run(
        ["python3", "scripts/browser_session_guard.py", "--help"],
        cwd=SKILL,
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Record and audit agent-owned browser page sessions" in result.stdout


def test_verifier_required_file_checks_pass() -> None:
    module = verifier_module()
    issues = module.check_static(SKILL)
    assert issues == []


def test_verifier_npm_snapshot_uses_primary_registry(monkeypatch) -> None:
    module = verifier_module()

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b'{"version":"1.4.0"}'

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://registry.npmjs.org/chrome-devtools-mcp/latest"
        assert timeout == 3.0
        return FakeResponse()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    result = module.check_npm_version("chrome-devtools-mcp", "1.4.0", 3.0)

    assert result["ok"] is True
    assert result["actual"] == "1.4.0"


def test_browser_private_paths_are_gitignored() -> None:
    paths = [
        ".localsetup-maint/ui-browser-profiles/chrome-devtools/Default/Cookies",
        ".localsetup-maint/ui-browser-artifacts/shot.png",
        ".localsetup-maint/ui-browser-sessions/session.json",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "-v", "--", *paths],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0
    for path in paths:
        assert path in result.stdout


def test_verifier_help_exits_cleanly() -> None:
    result = subprocess.run(
        ["python3", "scripts/verify_ui_browser_debugging_sources.py", "--help"],
        cwd=SKILL,
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Verify ls-ui-browser-debugging" in result.stdout
