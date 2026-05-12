import json
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "_localsetup" / "skills" / "ls-keepass-secrets" / "scripts" / "localsetup_secrets.py"
MAP = REPO / "_localsetup" / "skills" / "ls-keepass-secrets" / "examples" / "map.yaml"


def run_cli(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(CLI), *args],
        cwd=REPO,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def test_resolve_fake_redacts_password_by_default() -> None:
    result = run_cli("resolve", "admin@example.com", "--backend", "fake", "--map", str(MAP))
    data = payload(result)
    assert result.returncode == 0
    assert data["data"]["password"] == "<redacted>"
    assert data["data"]["_hint"].startswith("Use --show-sensitive")


def test_ensure_dry_run_and_apply(tmp_path: Path) -> None:
    store = tmp_path / "fake.json"
    dry = run_cli("ensure", "postgres.box03.app1", "--backend", "fake", "--map", str(MAP), "--fake-store", str(store))
    dry_data = payload(dry)
    assert dry.returncode == 0
    assert dry_data["warnings"]
    assert not store.exists()
    applied = run_cli(
        "ensure",
        "postgres.box03.app1",
        "--backend",
        "fake",
        "--map",
        str(MAP),
        "--fake-store",
        str(store),
        "--apply",
    )
    assert applied.returncode == 0
    assert store.exists()


def test_set_from_stdin_requires_apply(tmp_path: Path) -> None:
    store = tmp_path / "fake.json"
    result = run_cli(
        "set",
        "postgres.box03.app1",
        "password",
        "--stdin",
        "--backend",
        "fake",
        "--map",
        str(MAP),
        "--fake-store",
        str(store),
        "--apply",
        input_text="placeholder",
    )
    data = payload(result)
    assert result.returncode == 0
    assert data["data"]["changed"] is True


def test_rotate_and_delete_dry_run() -> None:
    rotated = run_cli("rotate", "postgres.box03.app1", "--backend", "fake", "--map", str(MAP))
    deleted = run_cli("delete", "postgres.box03.app1", "--backend", "fake", "--map", str(MAP))
    assert payload(rotated)["warnings"]
    assert payload(deleted)["warnings"]


def test_render_template_and_tracked_output_refusal(tmp_path: Path) -> None:
    template = tmp_path / "template.txt"
    template.write_text("pw={{secret:postgres.box03.app1:password}}\n", encoding="utf-8")
    default_rendered = run_cli("render-template", str(template), "--backend", "fake", "--map", str(MAP))
    default_payload = payload(default_rendered)
    assert default_payload["data"]["rendered"] == "<redacted>"
    assert "fake-postgres" not in default_rendered.stdout
    rendered = run_cli("render-template", str(template), "--backend", "fake", "--map", str(MAP), "--show-sensitive")
    assert "fake-postgres.box03.app1-password" in payload(rendered)["data"]["rendered"]
    refused = run_cli(
        "render-template",
        str(template),
        "--backend",
        "fake",
        "--map",
        str(MAP),
        "--show-sensitive",
        "--output",
        str(REPO / "README.md"),
    )
    refused_payload = payload(refused)
    assert refused.returncode != 0
    assert refused_payload["errors"][0]["code"] == "tracked_output_refused"
    untracked = run_cli(
        "render-template",
        str(template),
        "--backend",
        "fake",
        "--map",
        str(MAP),
        "--show-sensitive",
        "--output",
        str(REPO / "rendered-secrets.txt"),
    )
    untracked_payload = payload(untracked)
    assert untracked.returncode != 0
    assert untracked_payload["errors"][0]["code"] == "tracked_output_refused"
    ignored = run_cli(
        "render-template",
        str(template),
        "--backend",
        "fake",
        "--map",
        str(MAP),
        "--show-sensitive",
        "--output",
        str(REPO / ".env.rendered"),
    )
    assert ignored.returncode == 0
    assert payload(ignored)["data"]["would_write"] is True


def test_keepassxc_backend_methods_return_json_errors() -> None:
    result = run_cli("ensure", "postgres.box03.app1", "--backend", "keepassxc", "--map", str(MAP))
    data = payload(result)
    assert result.returncode != 0
    assert data["ok"] is False
    assert data["errors"][0]["code"] == "interactive_backend_required"
    assert "Traceback" not in result.stderr


def test_vault_backup_refuses_non_ignored_repo_target(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("backend: fake\ndatabase: README.md\n", encoding="utf-8")
    result = run_cli("vault-backup", "--config", str(config), "--output", str(REPO / "README.md.bak"))
    data = payload(result)
    assert result.returncode != 0
    assert data["errors"][0]["code"] == "tracked_output_refused"
