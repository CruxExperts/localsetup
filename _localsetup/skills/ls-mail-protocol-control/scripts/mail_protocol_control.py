#!/usr/bin/env python3
# Purpose: Policy-gated SMTP and IMAP control layer for delegated mail accounts.
# Created: 2026-03-07
# Last updated: 2026-03-07

from __future__ import annotations

import base64
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from crypto_engine import CryptoEngine, CryptoError  # type: ignore
    from mail_protocol_imap import ImapAdapter  # type: ignore
    from mail_protocol_support import (  # type: ignore
        ConfirmationStore,
        CredentialProvider,
        EnvCredentialProvider,
        MailControlError,
        SmtpAdapter,
        _scope_hash,
        build_envelope_from_payload,
        extract_encrypted_blob,
    )
    from mail_types import AccountConfig, MailResult  # type: ignore
    from mail_utils import as_bool, make_request_id, sanitize_text  # type: ignore
    from policy_engine import PolicyError, PolicyInputError, evaluate_action, load_policy  # type: ignore
else:
    from .crypto_engine import CryptoEngine, CryptoError
    from .mail_protocol_imap import ImapAdapter
    from .mail_protocol_support import (
        ConfirmationStore,
        CredentialProvider,
        EnvCredentialProvider,
        MailControlError,
        SmtpAdapter,
        _scope_hash,
        build_envelope_from_payload,
        extract_encrypted_blob,
    )
    from .mail_types import AccountConfig, MailResult
    from .mail_utils import as_bool, make_request_id, sanitize_text
    from .policy_engine import PolicyError, PolicyInputError, evaluate_action, load_policy

class MailProtocolControl:
    def __init__(
        self,
        policy_path: Path,
        accounts: list[AccountConfig],
        credential_provider: CredentialProvider | None = None,
        smtp_adapter: SmtpAdapter | None = None,
        imap_adapter: ImapAdapter | None = None,
    ):
        self.policy = load_policy(policy_path)
        self.accounts: dict[str, AccountConfig] = {a.account_id: a for a in accounts}
        self.credential_provider = credential_provider or EnvCredentialProvider()
        self.smtp = smtp_adapter or SmtpAdapter()
        self.imap = imap_adapter or ImapAdapter()
        self.confirmations = ConfirmationStore()
        self.idempotency_results: dict[str, dict[str, Any]] = {}
        self.crypto = CryptoEngine()

    def _account(self, account_id: str) -> AccountConfig:
        account = self.accounts.get(account_id)
        if not account:
            raise MailControlError(
                "ACCOUNT_NOT_FOUND", f"Account not found: {account_id}"
            )
        return account

    def _authorize(
        self,
        account_id: str,
        action: str,
        params: dict[str, Any],
        confirm_token: str | None = None,
        request_constraints: dict[str, Any] | None = None,
    ) -> None:
        decision = evaluate_action(
            self.policy,
            account_id,
            action,
            params=params,
            request_constraints=request_constraints,
        )
        if not decision.allowed:
            raise MailControlError("ACTION_BLOCKED", decision.reason)
        if decision.requires_confirmation:
            scope = _scope_hash(account_id, action, params)
            if not confirm_token:
                challenge = self.confirmations.issue(
                    account_id, action, scope, ttl_seconds=300
                )
                raise MailControlError(
                    "CONFIRMATION_REQUIRED",
                    f"Confirmation required. token={challenge['token']} expires_at={challenge['expires_at']}",
                )
            self.confirmations.consume(confirm_token, account_id, action, scope)

    def _credentials(self, account: AccountConfig) -> dict[str, str]:
        return self.credential_provider.get_auth_bundle(account.account_id)

    def _crypto_bundle(
        self, account_id: str, key_ref: str = "default"
    ) -> dict[str, str]:
        bundle = self.credential_provider.get_crypto_bundle(account_id, key_ref=key_ref)
        if not isinstance(bundle, dict):
            return {}
        return bundle

    def accounts_list(self) -> MailResult:
        rows = [asdict(a) for a in self.accounts.values()]
        return MailResult(ok=True, code="OK", data={"accounts": rows})

    def capabilities_get(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        account = self._account(account_id)
        creds = self._credentials(account)
        smtp_caps = self.smtp.verify_connectivity(account, creds)
        imap_caps = self.imap.get_capabilities(account, creds)
        return MailResult(
            ok=True,
            code="OK",
            data={"account_id": account_id, "smtp": smtp_caps, "imap": imap_caps},
        )

    def query(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        account = self._account(account_id)
        self._authorize(account_id, "imap.query_messages", payload)
        creds = self._credentials(account)
        data = self.imap.query_messages(account, creds, payload)
        data["next_actions"] = ["mail_get", "mail_get_attachment", "mail_mutate"]
        return MailResult(ok=True, code="OK", data=data)

    def get(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        account = self._account(account_id)
        action = (
            "imap.fetch_message_body"
            if as_bool(payload.get("detail"), False)
            else "imap.fetch_message_headers"
        )
        self._authorize(account_id, action, payload)
        creds = self._credentials(account)
        data = self.imap.get_message(account, creds, payload)
        data["next_actions"] = ["mail_get_attachment", "mail_mutate", "mail_reply_flow"]
        return MailResult(ok=True, code="OK", data=data)

    def get_attachment(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        account = self._account(account_id)
        self._authorize(account_id, "imap.fetch_attachment_content", payload)
        creds = self._credentials(account)
        data = self.imap.get_attachment(account, creds, payload)
        data["next_actions"] = ["mail_get_attachment"]
        return MailResult(ok=True, code="OK", data=data)

    def send(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        account = self._account(account_id)
        self._authorize(account_id, "smtp.send_message", payload)
        creds = self._credentials(account)
        data = self.smtp.send_message(account, creds, payload)
        return MailResult(ok=True, code="OK", data=data)

    def mutate(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        idempotency_key = sanitize_text(payload.get("idempotency_key"), 128)
        if idempotency_key and idempotency_key in self.idempotency_results:
            cached = self.idempotency_results[idempotency_key]
            return MailResult(
                ok=True, code="OK", data={**cached, "idempotent_replay": True}
            )
        mapping = {
            "set_flags": "imap.set_flags",
            "clear_flags": "imap.clear_flags",
            "copy_messages": "imap.copy_messages",
            "move_messages": "imap.move_messages",
            "delete_messages": "imap.delete_messages",
            "expunge_mailbox": "imap.expunge_mailbox",
            "create_mailbox": "imap.create_mailbox",
            "rename_mailbox": "imap.rename_mailbox",
            "delete_mailbox": "imap.delete_mailbox",
        }
        mutate_action = sanitize_text(payload.get("mutate_action"), 64)
        action = mapping.get(mutate_action)
        if not action:
            raise MailControlError("INVALID_ARGUMENT", "Unknown mutate_action.")
        account = self._account(account_id)
        confirm_token = sanitize_text(payload.get("confirm_token"), 128) or None
        self._authorize(account_id, action, payload, confirm_token=confirm_token)
        creds = self._credentials(account)
        result = self.imap.mutate(account, creds, payload)
        op_id = make_request_id()
        result["op_id"] = op_id
        if idempotency_key:
            self.idempotency_results[idempotency_key] = result
        return MailResult(ok=True, code="OK", data=result)

    def sync(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        self._authorize(account_id, "imap.sync_state", payload)
        cursor = sanitize_text(payload.get("cursor"), 128)
        now = int(time.time())
        next_cursor = base64.urlsafe_b64encode(
            f"{account_id}:{now}".encode("utf-8")
        ).decode("utf-8")
        return MailResult(
            ok=True,
            code="OK",
            data={
                "cursor": cursor or None,
                "next": next_cursor,
                "next_actions": ["mail_query"],
            },
        )

    def policy_preview(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        action = sanitize_text(payload.get("action"), 128)
        decision = evaluate_action(self.policy, account_id, action, params=payload)
        return MailResult(
            ok=True,
            code="OK",
            data={
                "allowed": decision.allowed,
                "reason": decision.reason,
                "requires_confirmation": decision.requires_confirmation,
                "allow_count": len(decision.effective_allow),
                "deny_count": len(decision.effective_deny),
            },
        )

    def encrypt_payload(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        self._authorize(account_id, "crypto.encrypt_payload", payload)
        mode = sanitize_text(payload.get("encryption_mode"), 32).lower()
        if not mode:
            raise MailControlError("INVALID_ARGUMENT", "encryption_mode is required.")
        key_ref = sanitize_text(payload.get("key_ref"), 64) or "default"
        envelope_obj: dict[str, Any]
        if isinstance(payload.get("envelope"), dict):
            envelope_obj = dict(payload["envelope"])
        else:
            envelope_obj = build_envelope_from_payload(payload).to_dict(
                include_attachment_content=True
            )
        secrets = self._crypto_bundle(account_id, key_ref=key_ref)
        encrypted = self.crypto.encrypt(mode, envelope_obj, secrets)
        return MailResult(
            ok=True, code="OK", data={"encrypted": encrypted, "mode": mode}
        )

    def decrypt_payload(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        self._authorize(account_id, "crypto.decrypt_payload", payload)
        encrypted = payload.get("encrypted")
        if not isinstance(encrypted, dict):
            raise MailControlError("INVALID_ARGUMENT", "encrypted object is required.")
        mode = sanitize_text(
            payload.get("encryption_mode") or encrypted.get("mode"), 32
        ).lower()
        if not mode:
            raise MailControlError("INVALID_ARGUMENT", "encryption_mode is required.")
        key_ref = sanitize_text(payload.get("key_ref"), 64) or "default"
        secrets = self._crypto_bundle(account_id, key_ref=key_ref)
        envelope = self.crypto.decrypt(mode, encrypted, secrets)
        include_attachment_content = as_bool(
            payload.get("include_attachment_content"), True
        )
        if not include_attachment_content and isinstance(
            envelope.get("attachments"), list
        ):
            reduced: list[dict[str, Any]] = []
            for row in envelope["attachments"]:
                if not isinstance(row, dict):
                    continue
                reduced.append(
                    {
                        "filename": sanitize_text(row.get("filename"), 256),
                        "content_type": sanitize_text(row.get("content_type"), 128),
                        "size": int(row.get("size", 0)),
                    }
                )
            envelope["attachments"] = reduced
        return MailResult(ok=True, code="OK", data={"envelope": envelope, "mode": mode})

    def send_encrypted(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        account = self._account(account_id)
        self._authorize(account_id, "smtp.send_encrypted", payload)
        # Agent Q strict gpg: caller supplies final openpgp armored blob (sign-then-encrypt)
        # so mail body is one layer only; recipient decrypt_openpgp yields JSON manifest.
        preencrypted = payload.get("preencrypted_openpgp_armored")
        if isinstance(preencrypted, str) and preencrypted.strip().startswith(
            "-----BEGIN PGP"
        ):
            armored = preencrypted.strip()
            if len(armored) > 10 * 1024 * 1024:
                return MailResult(
                    ok=False,
                    code="PAYLOAD_TOO_LARGE",
                    message="preencrypted_openpgp_armored exceeds 10MB cap.",
                )
            encrypted = {"mode": "openpgp", "armored": armored}
        else:
            encrypt_result = self.encrypt_payload(payload).to_dict()
            encrypted = encrypt_result.get("encrypted", {})
        creds = self._credentials(account)
        send_data = self.smtp.send_encrypted_payload(account, creds, payload, encrypted)
        send_data["encrypted"] = {"mode": encrypted.get("mode")}
        return MailResult(ok=True, code="OK", data=send_data)

    def get_decrypted(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        self._authorize(account_id, "imap.fetch_and_decrypt", payload)
        message = self.get(
            {
                "acct": account_id,
                "mailbox": payload.get("mailbox", "INBOX"),
                "id": payload.get("id"),
                "detail": True,
                "include_attachment_content": False,
            }
        ).to_dict()
        encrypted_blob = extract_encrypted_blob(message)
        decrypted = self.decrypt_payload(
            {
                "acct": account_id,
                "encrypted": encrypted_blob,
                "encryption_mode": payload.get("encryption_mode")
                or encrypted_blob.get("mode"),
                "key_ref": payload.get("key_ref"),
                "include_attachment_content": as_bool(
                    payload.get("include_attachment_content"), True
                ),
            }
        ).to_dict()
        return MailResult(
            ok=True, code="OK", data={"message": message, "decrypted": decrypted}
        )

    def triage_batch(self, payload: dict[str, Any]) -> MailResult:
        query_payload = dict(payload)
        query_payload.setdefault("lim", 25)
        queried = self.query(query_payload).to_dict()
        items = queried.get("items", [])
        uids = [
            item.get("id")
            for item in items
            if isinstance(item, dict) and item.get("id")
        ]
        target = sanitize_text(payload.get("target_mailbox"), 128)
        if not uids or not target:
            return MailResult(ok=True, code="OK", data={"queried": queried, "moved": 0})
        mutate_payload = {
            "acct": sanitize_text(payload.get("acct"), 64),
            "mailbox": sanitize_text(payload.get("mailbox", "INBOX"), 128),
            "mutate_action": "move_messages",
            "uids": uids,
            "target_mailbox": target,
            "count": len(uids),
            "confirm_token": sanitize_text(payload.get("confirm_token"), 128),
        }
        moved = self.mutate(mutate_payload).to_dict()
        return MailResult(
            ok=True,
            code="OK",
            data={"queried": queried, "mutation": moved, "moved": len(uids)},
        )

    def reply_flow(self, payload: dict[str, Any]) -> MailResult:
        account_id = sanitize_text(payload.get("acct"), 64)
        details = self.get(
            {
                "acct": account_id,
                "id": payload.get("id"),
                "mailbox": payload.get("mailbox", "INBOX"),
                "detail": True,
            }
        ).to_dict()
        original_from = sanitize_text(details.get("from"), 256)
        subject = sanitize_text(details.get("sub"), 256)
        reply_subject = (
            subject if subject.lower().startswith("re:") else f"Re: {subject}"
        )
        body = sanitize_text(payload.get("body"), 200000)
        sent = self.send(
            {
                "acct": account_id,
                "from": sanitize_text(payload.get("from"), 256),
                "to": [original_from],
                "subject": reply_subject,
                "body": body,
            }
        ).to_dict()
        return MailResult(ok=True, code="OK", data={"original": details, "sent": sent})

    def dispatch(self, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            if not isinstance(payload, dict):
                return MailResult(
                    ok=False,
                    code="INVALID_ARGUMENT",
                    message="Tool payload must be a JSON object.",
                ).to_dict()
            if tool == "mail_accounts_list":
                return self.accounts_list().to_dict()
            if tool == "mail_capabilities_get":
                return self.capabilities_get(payload).to_dict()
            if tool == "mail_query":
                return self.query(payload).to_dict()
            if tool == "mail_get":
                return self.get(payload).to_dict()
            if tool == "mail_get_attachment":
                return self.get_attachment(payload).to_dict()
            if tool == "mail_mutate":
                return self.mutate(payload).to_dict()
            if tool == "mail_send":
                return self.send(payload).to_dict()
            if tool == "mail_encrypt":
                return self.encrypt_payload(payload).to_dict()
            if tool == "mail_decrypt":
                return self.decrypt_payload(payload).to_dict()
            if tool == "mail_send_encrypted":
                return self.send_encrypted(payload).to_dict()
            if tool == "mail_get_decrypted":
                return self.get_decrypted(payload).to_dict()
            if tool == "mail_sync":
                return self.sync(payload).to_dict()
            if tool == "mail_policy_preview":
                return self.policy_preview(payload).to_dict()
            if tool == "mail_triage_batch":
                return self.triage_batch(payload).to_dict()
            if tool == "mail_reply_flow":
                return self.reply_flow(payload).to_dict()
            return MailResult(
                ok=False, code="UNKNOWN_TOOL", message=f"Unknown tool '{tool}'"
            ).to_dict()
        except MailControlError as exc:
            return MailResult(ok=False, code=exc.code, message=exc.message).to_dict()
        except PolicyInputError as exc:
            return MailResult(
                ok=False, code="INVALID_ARGUMENT", message=str(exc)
            ).to_dict()
        except PolicyError as exc:
            return MailResult(ok=False, code="POLICY_ERROR", message=str(exc)).to_dict()
        except CryptoError as exc:
            return MailResult(ok=False, code=exc.code, message=exc.message).to_dict()
        except (KeyError, TypeError, ValueError) as exc:
            return MailResult(
                ok=False, code="INVALID_ARGUMENT", message=str(exc)
            ).to_dict()
        except Exception as exc:  # noqa: BLE001
            return MailResult(
                ok=False, code="UNHANDLED_ERROR", message=str(exc)
            ).to_dict()
