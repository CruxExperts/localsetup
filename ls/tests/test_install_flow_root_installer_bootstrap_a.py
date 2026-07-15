from __future__ import annotations

from ls.tests.test_install_flow import *

def test_root_installer_piped_bootstrap_global_only_uses_managed_source(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo = make_bootstrap_git_repo(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "main",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    with install_path.open("rb") as stdin:
        completed = subprocess.run(
            ["bash", "-s", "--", "--non-interactive", "--yes", "--home", str(home)],
            cwd=outside,
            env=env,
            stdin=stdin,
            text=False,
            capture_output=True,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr.decode()
    assert (managed_source / "ls/tools/localsetup.py").is_file()
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
    assert (home / ".local/bin/localsetup").is_file()
    assert not (outside / ".codex").exists()
    assert not (outside / ".localsetup/lock.json").exists()


def test_root_installer_refreshes_clean_stale_managed_source_before_wizard(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo, legacy_commit, current_commit = make_bootstrap_git_repo_with_legacy_commit(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    subprocess.run(["git", "clone", str(bootstrap_repo), str(managed_source)], text=True, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "--detach", legacy_commit], cwd=managed_source, text=True, capture_output=True, check=True)
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "main",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = run_installer_in_pty(
        [str(install_path), "--home", str(home), "--no-register-shell"],
        input_text="\n\nq\n",
        cwd=outside,
        env=env,
    )

    combined = completed.stdout + completed.stderr
    refreshed = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert completed.returncode == 130, combined
    assert refreshed == current_commit
    assert "invalid choice: 'wizard'" not in combined


def test_root_installer_refreshes_clean_stale_managed_source_before_non_interactive_install(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo, legacy_commit, current_commit = make_bootstrap_git_repo_with_legacy_commit(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    subprocess.run(["git", "clone", str(bootstrap_repo), str(managed_source)], text=True, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "--detach", legacy_commit], cwd=managed_source, text=True, capture_output=True, check=True)
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "main",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = subprocess.run(
        [str(install_path), "--non-interactive", "--yes", "--home", str(home), "--no-register-shell"],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    refreshed = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert completed.returncode == 0, completed.stderr
    assert refreshed == current_commit
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()


def test_root_installer_discovers_latest_stable_release_tag_for_managed_source(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo, old_commit, current_commit = make_bootstrap_git_repo_with_release_tags(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    subprocess.run(["git", "clone", str(bootstrap_repo), str(managed_source)], text=True, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "--detach", old_commit], cwd=managed_source, text=True, capture_output=True, check=True)
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = subprocess.run(
        [str(install_path), "--non-interactive", "--yes", "--home", str(home), "--no-register-shell"],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    refreshed = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert completed.returncode == 0, completed.stderr
    assert refreshed == current_commit
    assert (managed_source / "README.md").read_text(encoding="utf-8") == "# Localsetup\n\nrelease refresh\n"
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()


def test_root_installer_filters_github_release_api_payload_before_tag_fallback(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo, _old_commit, current_commit = make_bootstrap_git_repo_with_release_tags(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    releases = tmp_path / "releases.json"
    outside.mkdir()
    releases.write_text(
        json.dumps(
            [
                {
                    "tag_name": "v4.9.0-rc.1",
                    "draft": False,
                    "prerelease": True,
                    "published_at": "2026-05-20T00:00:00Z",
                },
                {
                    "tag_name": "v4.8.10",
                    "draft": True,
                    "prerelease": False,
                    "published_at": "2026-05-19T03:00:00Z",
                },
                {
                    "tag_name": "v4.8.9",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-05-19T02:00:00Z",
                },
                {
                    "tag_name": "v4.8.7",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-05-18T02:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "",
        "LOCALSETUP_BOOTSTRAP_RELEASES_URL": releases.resolve().as_uri(),
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = subprocess.run(
        [str(install_path), "--non-interactive", "--yes", "--home", str(home), "--no-register-shell"],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    checked_out = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert completed.returncode == 0, completed.stderr
    assert checked_out == current_commit


def test_root_installer_bootstrap_ref_override_skips_latest_release_discovery(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo, old_commit, _current_commit = make_bootstrap_git_repo_with_release_tags(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(bootstrap_repo),
        "LOCALSETUP_BOOTSTRAP_REF": "v4.8.7",
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = subprocess.run(
        [str(install_path), "--non-interactive", "--yes", "--home", str(home), "--no-register-shell"],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    checked_out = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert completed.returncode == 0, completed.stderr
    assert checked_out == old_commit
    assert (managed_source / "README.md").read_text(encoding="utf-8") == "# Localsetup\n"


def test_root_installer_offline_release_lookup_reuses_existing_managed_source(tmp_path: Path) -> None:
    install_path = Path(__file__).resolve().parents[2] / "install"
    bootstrap_repo = make_bootstrap_git_repo(tmp_path / "bootstrap")
    outside = tmp_path / "outside"
    home = tmp_path / "home"
    managed_source = tmp_path / "managed-source"
    outside.mkdir()
    subprocess.run(["git", "clone", str(bootstrap_repo), str(managed_source)], text=True, capture_output=True, check=True)
    before = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    env = {
        **os.environ,
        "LOCALSETUP_BOOTSTRAP_REPO": str(tmp_path / "missing-remote"),
        "LOCALSETUP_BOOTSTRAP_SOURCE_DIR": str(managed_source),
    }

    completed = subprocess.run(
        [str(install_path), "--non-interactive", "--yes", "--home", str(home), "--no-register-shell"],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    after = subprocess.run(
        ["git", "-C", str(managed_source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert completed.returncode == 0, completed.stderr
    assert "failed to discover the latest Localsetup release; using existing managed source" in completed.stderr
    assert after == before
    assert (home / ".local/share/localsetup/packages/ls-context").is_dir()
