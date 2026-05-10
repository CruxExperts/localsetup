#!/usr/bin/env python3
# Purpose: Unit tests for attachment and crypto mail protocol control flows.
# Created: 2026-03-07
# Last updated: 2026-03-07

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import mcp_server
from scripts.crypto_engine import CryptoEngine, CryptoError
from scripts.mail_protocol_control import MailProtocolControl
from scripts.mail_types import AccountConfig
from scripts.mcp_server import BootstrapError, _load_accounts
from scripts.policy_engine import PolicyError, load_policy


class FakeCreds:
    def get_credential(self, account_id: str, field: str) -> str:
        return "x"

    def get_auth_bundle(self, account_id: str) -> dict[str, str]:
        return {"username": "u", "password": "p"}

    def get_crypto_bundle(
        self, account_id: str, key_ref: str = "default"
    ) -> dict[str, str]:
        return {
            "psk": "test-psk",
            "password_secret": "test-password-secret",
        }


class FakeSmtp:
    def verify_connectivity(
        self, account: AccountConfig, creds: dict[str, str]
    ) -> dict[str, str]:
        return {"mode": "starttls"}

    def send_message(
        self, account: AccountConfig, creds: dict[str, str], payload: dict[str, str]
    ) -> dict[str, object]:
        return {
            "accepted": ["a@example.com"],
            "attachment_count": len(payload.get("attachments", [])),
        }

    def send_encrypted_payload(
        self,
        account: AccountConfig,
        creds: dict[str, str],
        payload: dict[str, str],
        encrypted_blob: dict[str, str],
    ) -> dict[str, object]:
        return {
            "accepted": ["a@example.com"],
            "encryption_mode": encrypted_blob.get("mode", ""),
        }


class FakeImap:
    def get_capabilities(
        self, account: AccountConfig, creds: dict[str, str]
    ) -> dict[str, list[str]]:
        return {"capabilities": ["IMAP4REV1", "MOVE"]}

    def query_messages(
        self, account: AccountConfig, creds: dict[str, str], payload: dict[str, str]
    ) -> dict[str, object]:
        return {
            "items": [{"id": "1", "from": "x", "sub": "y", "dt": "z"}],
            "total": 1,
            "next": None,
        }

    def get_message(
        self, account: AccountConfig, creds: dict[str, str], payload: dict[str, str]
    ) -> dict[str, object]:
        if payload.get("id") == "encrypted":
            return {
                "id": "encrypted",
                "from": "x@example.com",
                "sub": "Hello",
                "dt": "Today",
                "body": '{"mode":"psk","ciphertext_b64":"aW52YWxpZA==","nonce_b64":"aW52YWxpZA==","salt_b64":"aW52YWxpZA=="}',
                "attachments": [],
            }
        return {
            "id": "1",
            "from": "x@example.com",
            "sub": "Hello",
            "dt": "Today",
            "attachments": [
                {
                    "attachment_index": 0,
                    "filename": "report.txt",
                    "size": 4,
                    "content_type": "text/plain",
                }
            ],
        }

    def get_attachment(
        self, account: AccountConfig, creds: dict[str, str], payload: dict[str, object]
    ) -> dict[str, object]:
        return {
            "id": str(payload.get("id", "1")),
            "attachment_index": int(payload.get("attachment_index", 0)),
            "filename": "report.txt",
            "content_type": "text/plain",
            "size": 4,
            "offset": 0,
            "chunk_size": 4,
            "content_bytes_base64": "dGVzdA==",
            "next_offset": None,
            "done": True,
        }

    def mutate(
        self, account: AccountConfig, creds: dict[str, str], payload: dict[str, object]
    ) -> dict[str, object]:
        return {
            "updated": len(payload.get("uids") or []),
            "action": payload.get("mutate_action", ""),
        }


def _write_policy(tmp_path: Path) -> Path:
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """
version: 1
default_profile: restricted
profiles:
  restricted:
    allow_actions:
      - smtp.*
      - imap.read.*
      - imap.write.*
      - crypto.*
    deny_actions: []
    thresholds:
      delete_count_confirm: 2
      move_count_confirm: 2
      expunge_requires_confirm: true
      folder_delete_requires_confirm: true
accounts:
  acct1:
    profile: restricted
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return policy


def _control(tmp_path: Path) -> MailProtocolControl:
    account = AccountConfig(
        account_id="acct1", smtp_host="smtp.local", imap_host="imap.local"
    )
    return MailProtocolControl(
        policy_path=_write_policy(tmp_path),
        accounts=[account],
        credential_provider=FakeCreds(),
        smtp_adapter=FakeSmtp(),
        imap_adapter=FakeImap(),
    )


def test_query_success(tmp_path: Path) -> None:
    control = _control(tmp_path)
    result = control.dispatch(
        "mail_query", {"acct": "acct1", "mailbox": "INBOX", "query": "ALL"}
    )
    assert result["ok"] is True
    assert result["code"] == "OK"
    assert result["items"][0]["id"] == "1"


def test_mutate_requires_confirmation(tmp_path: Path) -> None:
    control = _control(tmp_path)
    result = control.dispatch(
        "mail_mutate",
        {
            "acct": "acct1",
            "mailbox": "INBOX",
            "mutate_action": "move_messages",
            "uids": ["1", "2"],
            "target_mailbox": "Archive",
        },
    )
    assert result["ok"] is False
    assert result["code"] == "CONFIRMATION_REQUIRED"


def test_idempotency_replay(tmp_path: Path) -> None:
    control = _control(tmp_path)
    payload = {
        "acct": "acct1",
        "mailbox": "INBOX",
        "mutate_action": "set_flags",
        "uids": ["1"],
        "flags": "\\Seen",
        "idempotency_key": "abc123",
    }
    first = control.dispatch("mail_mutate", payload)
    second = control.dispatch("mail_mutate", payload)
    assert first["ok"] is True
    assert second["ok"] is True
    assert second["idempotent_replay"] is True


def test_policy_blocked(tmp_path: Path) -> None:
    control = _control(tmp_path)
    result = control.dispatch(
        "mail_mutate",
        {
            "acct": "acct1",
            "mailbox": "INBOX",
            "mutate_action": "delete_mailbox",
            "target_mailbox": "Old",
        },
    )
    assert result["ok"] is False
    assert result["code"] in {"ACTION_BLOCKED", "CONFIRMATION_REQUIRED"}


def test_unknown_tool(tmp_path: Path) -> None:
    control = _control(tmp_path)
    result = control.dispatch("mail_missing", {"acct": "acct1"})
    assert result["ok"] is False
    assert result["code"] == "UNKNOWN_TOOL"


def test_non_object_payload_returns_invalid_argument(tmp_path: Path) -> None:
    control = _control(tmp_path)
    result = control.dispatch(
        "mail_query", ["not", "an", "object"]  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert result["code"] == "INVALID_ARGUMENT"
    assert "JSON object" in result["message"]


def test_malformed_threshold_count_returns_invalid_argument(tmp_path: Path) -> None:
    control = _control(tmp_path)
    result = control.dispatch(
        "mail_mutate",
        {
            "acct": "acct1",
            "mailbox": "INBOX",
            "mutate_action": "move_messages",
            "uids": ["1"],
            "count": "many",
            "target_mailbox": "Archive",
        },
    )
    assert result["ok"] is False
    assert result["code"] == "INVALID_ARGUMENT"
    assert "count" in result["message"]


def test_send_supports_attachments(tmp_path: Path) -> None:
    control = _control(tmp_path)
    result = control.dispatch(
        "mail_send",
        {
            "acct": "acct1",
            "from": "x@example.com",
            "to": ["y@example.com"],
            "subject": "Attachment",
            "body": "payload",
            "attachments": [
                {
                    "filename": "report.txt",
                    "content_type": "text/plain",
                    "content_bytes_base64": "dGVzdA==",
                }
            ],
        },
    )
    assert result["ok"] is True
    assert result["attachment_count"] == 1


def test_get_attachment(tmp_path: Path) -> None:
    control = _control(tmp_path)
    result = control.dispatch(
        "mail_get_attachment",
        {"acct": "acct1", "mailbox": "INBOX", "id": "1", "attachment_index": 0},
    )
    assert result["ok"] is True
    assert result["filename"] == "report.txt"


def test_encrypt_decrypt_roundtrip_psk(tmp_path: Path) -> None:
    control = _control(tmp_path)
    encrypted = control.dispatch(
        "mail_encrypt",
        {
            "acct": "acct1",
            "encryption_mode": "psk",
            "from": "x@example.com",
            "to": ["y@example.com"],
            "subject": "Secure",
            "body": "hello",
            "attachments": [
                {
                    "filename": "report.txt",
                    "content_type": "text/plain",
                    "content_bytes_base64": "dGVzdA==",
                }
            ],
        },
    )
    assert encrypted["ok"] is True
    decrypted = control.dispatch(
        "mail_decrypt",
        {
            "acct": "acct1",
            "encryption_mode": "psk",
            "encrypted": encrypted["encrypted"],
            "include_attachment_content": False,
        },
    )
    assert decrypted["ok"] is True
    assert decrypted["envelope"]["headers"]["subject"] == "Secure"
    assert decrypted["envelope"]["attachments"][0]["filename"] == "report.txt"


def test_send_encrypted(tmp_path: Path) -> None:
    control = _control(tmp_path)
    result = control.dispatch(
        "mail_send_encrypted",
        {
            "acct": "acct1",
            "from": "x@example.com",
            "to": ["y@example.com"],
            "subject": "Secure",
            "body": "hello",
            "encryption_mode": "password",
        },
    )
    assert result["ok"] is True
    assert result["encryption_mode"] == "password"


def test_encrypt_mode_blocked_by_policy(tmp_path: Path) -> None:
    policy = tmp_path / "policy-mode.yaml"
    policy.write_text(
        """
version: 1
default_profile: restricted
profiles:
  restricted:
    allow_actions:
      - smtp.*
      - imap.read.*
      - imap.write.*
      - crypto.*
    deny_actions: []
    thresholds:
      delete_count_confirm: 2
      move_count_confirm: 2
      expunge_requires_confirm: true
      folder_delete_requires_confirm: true
    constraints:
      allowed_encryption_modes:
        - psk
accounts:
  acct1:
    profile: restricted
""".strip()
        + "\n",
        encoding="utf-8",
    )
    account = AccountConfig(
        account_id="acct1", smtp_host="smtp.local", imap_host="imap.local"
    )
    control = MailProtocolControl(
        policy_path=policy,
        accounts=[account],
        credential_provider=FakeCreds(),
        smtp_adapter=FakeSmtp(),
        imap_adapter=FakeImap(),
    )
    result = control.dispatch(
        "mail_encrypt",
        {
            "acct": "acct1",
            "encryption_mode": "password",
            "from": "x@example.com",
            "to": ["y@example.com"],
            "subject": "Blocked",
            "body": "body",
        },
    )
    assert result["ok"] is False
    assert result["code"] == "ACTION_BLOCKED"


def test_account_threshold_overrides_are_validated(tmp_path: Path) -> None:
    policy = tmp_path / "policy-invalid-account-threshold.yaml"
    policy.write_text(
        """
version: 1
default_profile: restricted
profiles:
  restricted:
    allow_actions:
      - imap.*
    deny_actions: []
accounts:
  acct1:
    profile: restricted
    thresholds:
      delete_count_confirm: many
""".strip()
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyError) as excinfo:
        load_policy(policy)
    assert "account 'acct1'" in str(excinfo.value)
    assert "delete_count_confirm" in str(excinfo.value)


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


def test_password_decrypt_rejects_unbounded_pbkdf2_iterations() -> None:
    engine = CryptoEngine()
    encrypted = {
        "mode": "password",
        "salt_b64": "AAAAAAAAAAAAAAAAAAAAAA==",
        "nonce_b64": "AAAAAAAAAAAAAAAA",
        "ciphertext_b64": "AAAAAAAAAAAAAAAA",
        "iterations": 999999999,
    }
    with pytest.raises(CryptoError) as excinfo:
        engine.decrypt_password(encrypted, "secret")
    assert excinfo.value.code == "INVALID_CRYPTO_PARAMETER"
