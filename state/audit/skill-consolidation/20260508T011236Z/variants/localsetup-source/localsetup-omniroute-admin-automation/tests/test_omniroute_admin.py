import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

LIB_ROOT = Path(__file__).resolve().parents[1] / "scripts" / "lib" / "omniroute_admin"
UTIL_PATH = LIB_ROOT / "util.py"

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "omniroute_admin.py"
CLIENT_PATH = ROOT / "scripts" / "lib" / "omniroute_admin" / "client.py"
VALIDATE_PATH = ROOT / "scripts" / "lib" / "omniroute_admin" / "validate.py"
RECONCILE_PATH = ROOT / "scripts" / "lib" / "omniroute_admin" / "reconcile.py"

# Ensure package imports work for relative imports inside module files.
sys.path.insert(0, str(ROOT / "scripts"))


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_manifest_accepts_minimal_structure():
    validate_mod = _load_module(VALIDATE_PATH, "validate_mod")
    issues = validate_mod.validate_desired_manifest(
        {
            "providers": [{"id": "openai", "enabled": True}],
            "combos": [{"name": "combo-openai-gpt5.4"}],
            "usage_budget": {
                "owner_id": "team-data-eng",
                "owner_type": "team",
                "period": "monthly",
                "monthlyLimit": 500000,
                "alertThreshold": 0.8,
                "enforce": True,
            },
        }
    )
    assert issues == []


def test_validate_manifest_rejects_invalid_threshold():
    validate_mod = _load_module(VALIDATE_PATH, "validate_mod2")
    issues = validate_mod.validate_desired_manifest(
        {"usage_budget": {"alertThreshold": 1.8}}
    )
    assert any("alertThreshold" in issue for issue in issues)


def test_validate_manifest_accepts_budget_template_shape():
    validate_mod = _load_module(VALIDATE_PATH, "validate_mod_budget")
    issues = validate_mod.validate_desired_manifest(
        {
            "usage_budget": {
                "owner_id": "team-data-eng",
                "owner_type": "team",
                "period": "monthly",
                "monthlyLimit": 500000,
                "alertThreshold": 0.8,
                "enforce": True,
            }
        }
    )
    assert issues == []


def test_validate_manifest_rejects_incomplete_budget_shape():
    validate_mod = _load_module(VALIDATE_PATH, "validate_mod_budget_bad")
    issues = validate_mod.validate_desired_manifest(
        {
            "usage_budget": {
                "owner_id": "team-data-eng",
                "period": "monthly",
                "monthlyLimit": 500000,
            }
        }
    )
    assert any("missing required key" in issue for issue in issues)


def test_client_rejects_invalid_base_url():
    client_mod = _load_module(CLIENT_PATH, "client_mod")
    try:
        client_mod.OmniRouteAdminClient(
            base_url="ftp://localhost",
            api_key=None,
            management_cookie=None,
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "OmniRoute administration automation CLI" in result.stdout


def test_redact_payload_masks_sensitive_values():
    util_mod = _load_module(UTIL_PATH, "util_mod")
    payload = {
        "api_key": "sk-secret",
        "Authorization": "Bearer topsecret",
        "nested": {"token": "abc"},
        "normal": "ok",
    }
    redacted = util_mod.redact_payload(payload)
    assert redacted["api_key"] == "***REDACTED***"
    assert redacted["Authorization"] == "***REDACTED***"
    assert redacted["nested"]["token"] == "***REDACTED***"
    assert redacted["normal"] == "ok"


def test_redact_string_masks_embedded_patterns():
    util_mod = _load_module(UTIL_PATH, "util_mod_string")
    text = "authorization=Bearer abc123 api_key=sk-test-123 token=xyz"
    redacted = util_mod.redact_payload(text)
    assert "abc123" not in redacted
    assert "sk-test-123" not in redacted
    assert "token=xyz" not in redacted.lower()


def test_reconcile_alias_live_key_mapping():
    reconcile_mod = importlib.import_module("lib.omniroute_admin.reconcile")
    live = {
        "providers": [],
        "combos": [],
        "keys": [],
        "usage_budget": {},
        "model_aliases": [
            {"alias": "my-fast-model", "provider": "openai", "model": "gpt-4o-mini"}
        ],
    }
    desired = {
        "aliases": [
            {"alias": "my-fast-model", "provider": "openai", "model": "gpt-4o-mini"}
        ]
    }
    plan = reconcile_mod.build_plan(live, desired)
    assert plan.get("blocked") is False
    assert plan.get("summary", {}).get("total") == 0


def test_reconcile_normalization_ignores_server_managed_fields():
    reconcile_mod = importlib.import_module("lib.omniroute_admin.reconcile")
    live = {
        "providers": [
            {
                "id": "openai",
                "enabled": True,
                "createdAt": "2026-01-01T00:00:00Z",
                "stats": {"requests": 100},
            }
        ],
        "combos": [],
        "keys": [],
        "usage_budget": {},
        "model_aliases": [],
    }
    desired = {
        "providers": [
            {
                "id": "openai",
                "enabled": True,
            }
        ]
    }
    plan = reconcile_mod.build_plan(live, desired)
    assert plan.get("summary", {}).get("total") == 0


def test_guarded_mode_keeps_safe_ops_when_destructive_present():
    reconcile_mod = importlib.import_module("lib.omniroute_admin.reconcile")

    class DummyClient:
        def __init__(self):
            self.calls = []

        def create_resource(self, endpoint, payload):
            self.calls.append(("create", endpoint))
            return {"ok": True}

        def update_resource(self, endpoint, payload):
            self.calls.append(("update", endpoint))
            return {"ok": True}

        def patch(self, endpoint, payload):
            self.calls.append(("patch", endpoint))
            return {"ok": True}

        def post(self, endpoint, payload):
            self.calls.append(("post", endpoint))
            return {"ok": True}

        def delete_resource(self, endpoint):
            self.calls.append(("delete", endpoint))
            return {"ok": True}

    plan = {
        "blocked": False,
        "operations": [
            {
                "resource": "providers",
                "endpoint": "/api/providers",
                "action": "update",
                "id": "openai",
                "payload": {"id": "openai", "enabled": True},
                "destructive": False,
                "method": "PUT",
            },
            {
                "resource": "providers",
                "endpoint": "/api/providers",
                "action": "delete",
                "id": "old-provider",
                "payload": {"id": "old-provider"},
                "destructive": True,
                "method": "DELETE",
            },
        ],
    }

    client = DummyClient()
    result = reconcile_mod.apply_plan(client, plan, allow_destructive=False)
    assert result["applied_count"] == 1
    assert result["failed_count"] == 0
    assert result["skipped_destructive_count"] == 1
    assert result["status"] == "partial_success"
    assert any(item[0] in {"update", "patch", "post"} for item in client.calls)
    assert not any(item[0] == "delete" for item in client.calls)


def test_cli_validate_bad_json(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("not-json", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", "--desired", str(bad)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode in {1, 2}
