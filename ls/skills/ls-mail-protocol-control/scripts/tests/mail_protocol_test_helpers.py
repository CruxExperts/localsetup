from __future__ import annotations

from pathlib import Path

from scripts.mail_protocol_control import MailProtocolControl
from scripts.mail_types import AccountConfig


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


def write_policy(tmp_path: Path) -> Path:
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


def control(tmp_path: Path) -> MailProtocolControl:
    account = AccountConfig(
        account_id="acct1", smtp_host="smtp.local", imap_host="imap.local"
    )
    return MailProtocolControl(
        policy_path=write_policy(tmp_path),
        accounts=[account],
        credential_provider=FakeCreds(),
        smtp_adapter=FakeSmtp(),
        imap_adapter=FakeImap(),
    )
