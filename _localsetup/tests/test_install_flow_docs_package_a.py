from __future__ import annotations

from _localsetup.tests.test_install_flow import *

def test_skill_smoke_runner_uses_current_python_without_shell(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    script = Path(__file__).resolve().parents[2] / "_localsetup/skills/ls-skill-sandbox-tester/scripts/run_smoke.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--sandbox-dir",
            str(sandbox),
            "--command",
            "python -c 'import sys; print(sys.executable)'",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == sys.executable


def test_agent_context_and_markdown_report(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    config = InstallConfig(platforms=["codex"], packs=["core"], dependency_mode="prompt-only")

    context = build_agent_context(root, home=home, config=config)
    markdown = render_markdown_report(context)

    assert {"environment", "selected_platforms", "dependencies", "migration", "actions", "blockers", "warnings", "commands", "rollback", "verification"} <= set(context)
    assert context["selected_platforms"] == ["codex"]
    assert context["selected_packs"] == ["core"]
    assert "# Localsetup Install Context" in markdown
    assert "localsetup verify --platforms codex" in markdown
    assert "python3 _localsetup/tools/localsetup.py verify" not in markdown


def test_cli_doctor_target_warning_requires_explicit_target(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target-repo"
    target.mkdir()
    tool = root / "_localsetup" / "tools" / "localsetup.py"

    plain = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "doctor",
            "--dependency-mode",
            "prompt-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    explicit = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "--target-directory",
            str(target),
            "doctor",
            "--dependency-mode",
            "prompt-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    plain_payload = json.loads(plain.stdout)
    explicit_payload = json.loads(explicit.stdout)
    assert not any("target directory was provided" in warning for warning in plain_payload["warnings"])
    assert any("target directory was provided" in warning for warning in explicit_payload["warnings"])


def test_cli_context_target_warning_requires_explicit_target(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    target = tmp_path / "target-repo"
    target.mkdir()
    tool = root / "_localsetup" / "tools" / "localsetup.py"

    plain = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "context",
            "--dependency-mode",
            "prompt-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    explicit = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "--target-directory",
            str(target),
            "context",
            "--dependency-mode",
            "prompt-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    plain_payload = json.loads(plain.stdout)
    explicit_payload = json.loads(explicit.stdout)
    assert not any("target directory was provided" in warning for warning in plain_payload["warnings"])
    assert any("target directory was provided" in warning for warning in explicit_payload["warnings"])


def test_self_refresh_defaults_to_all_packs_and_existing_repo_adapters(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    tool = root / "_localsetup" / "tools" / "localsetup.py"

    existing_global = home / ".local" / "share" / "localsetup" / "packages"
    existing_global.mkdir(parents=True, exist_ok=True)
    (root / ".codex").mkdir(parents=True, exist_ok=True)
    (root / ".codex" / "skills").symlink_to(existing_global, target_is_directory=True)
    external_global = home / ".external" / "skills"
    external_global.mkdir(parents=True, exist_ok=True)
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor" / "skills").symlink_to(external_global, target_is_directory=True)

    completed = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "self-refresh",
            "--dependency-mode",
            "prompt-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["selected"]["platforms"] == ["codex"]
    assert "integrations" in payload["selected"]["packs"]
    assert (home / ".local/share/localsetup/packages/ls-cloudflare-dns").is_dir()
    assert_scoped_adapter(root / ".codex" / "skills", "ls-context")
    assert payload["verify"]["adapters"][0]["is_scoped_symlink_adapter"] is True
    assert (root / ".cursor" / "skills").resolve() == external_global


def test_self_refresh_preserves_existing_portable_adapter_mode(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    tool = root / "_localsetup" / "tools" / "localsetup.py"

    portable_adapter = root / ".codex" / "skills"
    portable_adapter.mkdir(parents=True, exist_ok=True)
    (portable_adapter / ".localsetup-portable").write_text("managed_by=localsetup\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--repo",
            str(root),
            "--home",
            str(home),
            "self-refresh",
            "--dependency-mode",
            "prompt-only",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["selected"]["platforms"] == ["codex"]
    assert payload["selected"]["attach_mode"] == "portable"
    assert portable_adapter.is_dir()
    assert not portable_adapter.is_symlink()
    assert (portable_adapter / ".localsetup-portable").is_file()


def test_docs_do_not_show_selector_free_portable_install() -> None:
    root = Path(__file__).resolve().parents[2]
    overview = (root / "_localsetup" / "docs" / "migration" / "overview.md").read_text(encoding="utf-8")

    assert "install --mode portable --apply" not in overview
    assert "install --mode portable --platforms codex --apply" in overview


def test_docs_and_package(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    (root / "_localsetup" / "__pycache__").mkdir()
    (root / "_localsetup" / "__pycache__" / "cached.pyc").write_bytes(b"bytecode")
    (root / "_localsetup" / ".cache" / "scrapling" / "jobs").mkdir(parents=True)
    (root / "_localsetup" / ".cache" / "scrapling" / "jobs" / "job.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (root / "_localsetup" / ".ruff_cache").mkdir()
    (root / "_localsetup" / ".ruff_cache" / "cache.bin").write_bytes(b"cache")
    (root / "_localsetup" / "docs" / "local-context").mkdir(parents=True)
    (root / "_localsetup" / "docs" / "local-context" / "SECRETS_OVERVIEW.md").write_text(
        "Secret ID: mail.box03.example.admin\n",
        encoding="utf-8",
    )
    (root / "_localsetup" / "cached.pyo").write_bytes(b"bytecode")
    npm_token_dir = (
        root
        / "_localsetup"
        / "skills"
        / "ls-npm-management"
        / "scripts"
        / "data"
        / "127_0_0_1_81"
        / "token"
    )
    npm_token_dir.mkdir(parents=True, exist_ok=True)
    (npm_token_dir / "token.txt").write_text("runtime-token\n", encoding="utf-8")
    (npm_token_dir / "expiry.txt").write_text("2099-01-01T00:00:00Z\n", encoding="utf-8")
    workflow_data_dir = (
        root
        / "_localsetup"
        / "workflows"
        / "ls-workflow-ops-tmux-session"
        / "scripts"
        / "data"
    )
    workflow_data_dir.mkdir(parents=True, exist_ok=True)
    (workflow_data_dir / "runtime.txt").write_text("workflow runtime\n", encoding="utf-8")
    (root / "state").mkdir()
    (root / "state" / "inventory.yml").write_text("private inventory\n", encoding="utf-8")
    docs = generate_alias_outputs(root)
    assert docs["count"] > 0
    assert (root / "_localsetup/docs/_generated/workflow-catalog.json").is_file()

    artifact = tmp_path / "localsetup-public.tar.gz"
    package = build_public_artifact(root, artifact)
    assert artifact.exists()
    assert package["leaks"] == []
    assert Path(package["sha256"]).is_file()
    assert Path(package["sbom"]).is_file()
    verified = verify_release_artifact(artifact, expected_commit=package["manifest"]["source_commit"])
    assert verified["ok"] is True
    assert any(check["name"] == "sbom" and check["ok"] for check in verified["checks"])
    assert verified["metadata"]["pack_id"] == "localsetup"
    for asset in (
        "assets/README.md",
        "assets/localsetup-readme-hero.svg",
        "assets/localsetup-architecture.svg",
        "assets/localsetup-install-lifecycle.svg",
    ):
        assert asset in package["files"]
    assert "assets" in package["manifest"]["public_paths"]
    assert "_localsetup/__pycache__/cached.pyc" not in package["files"]
    assert "_localsetup/.cache/scrapling/jobs/job.json" not in package["files"]
    assert "_localsetup/docs/local-context/SECRETS_OVERVIEW.md" not in package["files"]
    assert "_localsetup/.ruff_cache/cache.bin" not in package["files"]
    assert "_localsetup/cached.pyo" not in package["files"]
    assert "_localsetup/skills/ls-npm-management/scripts/data/127_0_0_1_81/token/token.txt" not in package["files"]
    assert "_localsetup/skills/ls-npm-management/scripts/data/127_0_0_1_81/token/expiry.txt" not in package["files"]
    assert "_localsetup/workflows/ls-workflow-ops-tmux-session/scripts/data/runtime.txt" not in package["files"]
    assert "state/inventory.yml" not in package["files"]


def test_package_command_creates_output_parent(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    artifact = tmp_path / "missing" / "nested" / "localsetup-public.tar.gz"

    package = build_public_artifact(root, artifact)

    assert artifact.is_file()
    assert Path(package["sha256"]).is_file()
    assert Path(package["sbom"]).is_file()


def test_package_command_fails_when_leak_scan_finds_private_file(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    tool = root / "_localsetup" / "tools" / "localsetup.py"
    leak = root / "_localsetup" / "token.secret"
    leak.write_text("do not ship\n", encoding="utf-8")
    artifact = tmp_path / "localsetup-public.tar.gz"

    completed = subprocess.run(
        [sys.executable, str(tool), "--repo", str(root), "package", "--out", str(artifact)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert "_localsetup/token.secret" in payload["leaks"]


def test_verify_release_rejects_missing_or_stale_sbom(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    artifact = tmp_path / "localsetup-public.tar.gz"
    package = build_public_artifact(root, artifact)
    sbom = Path(package["sbom"])
    sbom.unlink()

    missing = verify_release_artifact(artifact)
    assert missing["ok"] is False
    assert any(check["name"] == "sbom" and not check["ok"] for check in missing["checks"])

    sbom.write_text('{"bomFormat":"CycloneDX","metadata":{"component":{"name":"wrong"},"properties":[]},"components":[]}\n', encoding="utf-8")
    stale = verify_release_artifact(artifact)
    assert stale["ok"] is False
    assert any(check["name"] == "sbom" and not check["ok"] for check in stale["checks"])


def test_verify_release_rejects_incomplete_sbom_components(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)
    artifact = tmp_path / "localsetup-public.tar.gz"
    package = build_public_artifact(root, artifact)
    sbom = Path(package["sbom"])
    payload = json.loads(sbom.read_text(encoding="utf-8"))
    payload["components"] = payload["components"][:-1]
    sbom.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    verified = verify_release_artifact(artifact)

    assert verified["ok"] is False
    sbom_check = next(check for check in verified["checks"] if check["name"] == "sbom")
    assert sbom_check["missing_components"]


def test_parse_sha256_file_accepts_binary_mode_marker(tmp_path: Path) -> None:
    sha = tmp_path / "artifact.sha256"
    sha.write_text("a" * 64 + " *artifact.tar.gz\n", encoding="utf-8")
    digest, name = parse_sha256_file(sha)
    assert digest == "a" * 64
    assert name == "artifact.tar.gz"


def test_workflow_catalog_generation_parity_between_paths(tmp_path: Path) -> None:
    root = make_temp_repo(tmp_path)

    subprocess.run(
        [sys.executable, str(root / "_localsetup/tools/generate_docs_artifacts.py"), "--repo-root", str(root)],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    generated_by_script = json.loads(
        (root / "_localsetup/docs/_generated/workflow-catalog.json").read_text(encoding="utf-8")
    )
    taxonomy_by_script = json.loads(
        (root / "_localsetup/docs/_generated/skill-taxonomy.json").read_text(encoding="utf-8")
    )

    generate_alias_outputs(root)
    generated_by_v3_docs = json.loads(
        (root / "_localsetup/docs/_generated/workflow-catalog.json").read_text(encoding="utf-8")
    )
    taxonomy_by_v3_docs = json.loads(
        (root / "_localsetup/docs/_generated/skill-taxonomy.json").read_text(encoding="utf-8")
    )

    generated_by_script.pop("provenance", None)
    generated_by_v3_docs.pop("provenance", None)
    taxonomy_by_script.pop("provenance", None)
    taxonomy_by_v3_docs.pop("provenance", None)
    assert generated_by_script == workflow_catalog_payload(root)
    assert generated_by_v3_docs == workflow_catalog_payload(root)
    assert taxonomy_by_script == skill_taxonomy_payload(root)
    assert taxonomy_by_v3_docs == skill_taxonomy_payload(root)


def test_lifecycle_status_for_deprecated_and_private_docs() -> None:
    root = Path(__file__).resolve().parents[2]
    review_spec = (root / "_localsetup/docs/WORKFLOW_SKILLS_REVIEW_BUILD_SPEC.md").read_text(encoding="utf-8")
    assert "status: DEPRECATED" in review_spec

    docs_config = (root / "docs.config.yaml").read_text(encoding="utf-8")
    assert 'root: "_localsetup/docs/"' in docs_config
    assert '- "local-context/**"' in docs_config
    assert '- "version"' in docs_config
