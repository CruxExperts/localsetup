from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from ls.core.client_registry import compare_variants, load_client_registry


ROOT = Path(__file__).resolve().parents[2]


def test_codex_and_opencode_drift_is_deterministic_and_semantic() -> None:
    registry = load_client_registry(ROOT)
    codex = registry.variant("codex", "codex-cli")
    opencode = registry.variant("opencode", "opencode-cli")

    first = compare_variants(codex, opencode)
    second = compare_variants(codex, opencode)

    assert first == second
    assert first["left"] == "codex/codex-cli"
    assert first["right"] == "opencode/opencode-cli"
    assert first["rows"] == sorted(first["rows"], key=lambda row: row["capability"])
    assert first["overall_state"] == "partial"
    assert first["mismatch_count"] > 0
    assert first["state_vocabulary"] == [
        "verified",
        "partial",
        "experimental",
        "unsupported",
        "unknown",
    ]

    goal = next(row for row in first["rows"] if row["capability"] == "goal.status")
    assert goal["left"] == "supported"
    assert goal["right"] == "unverified"
    assert goal["state"] == "partial"
    assert not any(
        key in {"path", "commands", "executable", "executables", "ownership"}
        for row in first["rows"]
        for key in row
    )


def test_identical_variant_has_no_mismatches_and_keeps_incomplete_evidence_conservative() -> None:
    registry = load_client_registry(ROOT)
    report = compare_variants(
        registry.variant("codex", "codex-cli"),
        registry.variant("codex", "codex-cli"),
    )

    assert report["left"] == report["right"] == "codex/codex-cli"
    assert report["mismatch_count"] == 0
    assert all(row["matches"] for row in report["rows"])
    assert report["overall_state"] == "unknown"
    assert "declarations only" in report["limitation"]
    assert "runtime parity" in report["limitation"]


def test_client_registry_drift_cli_emits_stable_json() -> None:
    tool = ROOT / "ls" / "tools" / "localsetup.py"
    result = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--source-root",
            str(ROOT),
            "client-registry",
            "drift",
            "--left",
            "codex/codex-cli",
            "--right",
            "opencode/opencode-cli",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == compare_variants(
        load_client_registry(ROOT).variant("codex", "codex-cli"),
        load_client_registry(ROOT).variant("opencode", "opencode-cli"),
    )


def test_client_registry_drift_cli_rejects_invalid_canonical_key() -> None:
    tool = ROOT / "ls" / "tools" / "localsetup.py"
    result = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--source-root",
            str(ROOT),
            "client-registry",
            "drift",
            "--left",
            "codex/not-a-variant",
            "--right",
            "opencode/opencode-cli",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "unknown client registry variant" in result.stderr
    assert "codex/not-a-variant" in result.stderr


def test_client_registry_drift_cli_rejects_malformed_canonical_key() -> None:
    tool = ROOT / "ls" / "tools" / "localsetup.py"
    result = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--source-root",
            str(ROOT),
            "client-registry",
            "drift",
            "--left",
            "Codex/codex_cli",
            "--right",
            "opencode/opencode-cli",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "invalid client registry key" in result.stderr
    assert "Codex/codex_cli" in result.stderr
