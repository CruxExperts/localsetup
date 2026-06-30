from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "_localsetup" / "skills" / "ls-ui-browser-debugging"


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


def test_ui_browser_debugging_skill_is_registered() -> None:
    skill_md = SKILL / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert frontmatter["name"] == "ls-ui-browser-debugging"
    assert "UI review and browser-driven debugging workflow" in frontmatter["description"]
    assert frontmatter["metadata"]["version"] == "1.0"

    pack = yaml.safe_load((ROOT / "_localsetup" / "config" / "pack.yaml").read_text(encoding="utf-8"))
    assert "ls-ui-browser-debugging" in pack["packs"]["dev"]
    assert pack["extensions"]["skill_taxonomy"]["ls-ui-browser-debugging"] == {
        "class": "development",
        "sort_priority": 30,
        "tags": ["ui", "browser", "debugging", "mcp"],
        "owner_scope": "skill",
    }

    smoke = yaml.safe_load((ROOT / "_localsetup" / "tests" / "skill_smoke_commands.yaml").read_text(encoding="utf-8"))
    assert smoke["ls-ui-browser-debugging"] == "python3 scripts/verify_ui_browser_debugging_sources.py --help"


def test_ui_browser_debugging_required_files_exist() -> None:
    required = [
        "references/source-ledger.md",
        "references/mcp-bootstrap-and-repair.md",
        "references/browser-session-management.md",
        "references/ui-feasibility-review.md",
        "references/subagent-browser-workflows.md",
        "references/browser-mcp-landscape.md",
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


def test_environment_standard_config_uses_privacy_oriented_args() -> None:
    module = env_module()
    config = module.standard_config()

    assert config["command"] == "npx"
    assert config["args"][:2] == ["-y", "chrome-devtools-mcp@latest"]
    assert "--no-usage-statistics" in config["args"]
    assert "--no-performance-crux" in config["args"]
    assert "--redactNetworkHeaders" in config["args"]
    assert config["pinned_reproducibility_snapshot"]["version"] == "1.4.0"


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
