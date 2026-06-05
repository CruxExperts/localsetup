#!/usr/bin/env python3
"""MCP bootstrap/error tests for mail protocol control."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import mcp_server
from scripts.mcp_server import BootstrapError, _load_accounts
from mail_protocol_test_helpers import control as _control


def test_load_accounts_rejects_malformed_port(tmp_path: Path) -> None:
    accounts = tmp_path / "mail_accounts.json"
    accounts.write_text(
        json.dumps(
            [
                {
                    "account_id": "support",
                    "smtp_host": "smtp.example.com",
                    "smtp_port": "not-a-port",
                    "imap_host": "imap.example.com",
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(BootstrapError) as excinfo:
        _load_accounts(accounts)
    assert excinfo.value.code == "ACCOUNT_CONFIG_INVALID_FIELD"
    assert "smtp_port" in excinfo.value.message


def test_load_accounts_rejects_duplicate_account_ids(tmp_path: Path) -> None:
    accounts = tmp_path / "mail_accounts.json"
    accounts.write_text(
        json.dumps(
            [
                {
                    "account_id": "support",
                    "smtp_host": "smtp.example.com",
                    "imap_host": "imap.example.com",
                },
                {
                    "account_id": "support",
                    "smtp_host": "smtp2.example.com",
                    "imap_host": "imap2.example.com",
                },
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(BootstrapError) as excinfo:
        _load_accounts(accounts)
    assert excinfo.value.code == "ACCOUNT_CONFIG_DUPLICATE_ACCOUNT"


def test_mcp_bootstrap_reports_account_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    accounts = tmp_path / "mail_accounts.json"
    accounts.write_text('{"not": "a list"}', encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mcp_server.py",
            "--policy",
            str(tmp_path / "missing-policy.yaml"),
            "--accounts",
            str(accounts),
            "--tool",
            "mail_accounts_list",
        ],
    )
    assert mcp_server.main() == 1
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert output["code"] == "ACCOUNT_CONFIG_INVALID_ROOT"


def test_mcp_bootstrap_reports_invalid_args_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mcp_server.py",
            "--policy",
            str(tmp_path / "missing-policy.yaml"),
            "--accounts",
            str(tmp_path / "missing-accounts.json"),
            "--tool",
            "mail_accounts_list",
            "--args-json",
            "{bad json",
        ],
    )

    assert mcp_server.main() == 1
    output = json.loads(capsys.readouterr().out)

    assert output["ok"] is False
    assert output["code"] == "ARGS_JSON_INVALID_JSON"


def test_mcp_bootstrap_reports_non_object_args_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mcp_server.py",
            "--policy",
            str(tmp_path / "missing-policy.yaml"),
            "--accounts",
            str(tmp_path / "missing-accounts.json"),
            "--tool",
            "mail_accounts_list",
            "--args-json",
            '["not", "object"]',
        ],
    )

    assert mcp_server.main() == 1
    output = json.loads(capsys.readouterr().out)

    assert output["ok"] is False
    assert output["code"] == "ARGS_JSON_INVALID_ROOT"


def test_dispatch_unhandled_error_fallback_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = _control(tmp_path)

    def raise_unexpected() -> object:
        raise RuntimeError("unexpected adapter failure")

    monkeypatch.setattr(control, "accounts_list", raise_unexpected)

    result = control.dispatch("mail_accounts_list", {})

    assert result["ok"] is False
    assert result["code"] == "UNHANDLED_ERROR"
    assert "unexpected adapter failure" in result["message"]
