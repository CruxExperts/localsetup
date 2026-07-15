"""Credential, confirmation, attachment, and SMTP helpers."""

from __future__ import annotations

import base64
import json
import os
import smtplib
import ssl
import time
import uuid
from email.message import EmailMessage
from typing import Any, Protocol

try:
    from .mail_types import AccountConfig, AttachmentItem, MessageEnvelope
    from .mail_utils import clamp_int, hash_text, require_fields, sanitize_list, sanitize_text
except ImportError:  # pragma: no cover - direct script import compatibility
    from mail_types import AccountConfig, AttachmentItem, MessageEnvelope  # type: ignore
    from mail_utils import clamp_int, hash_text, require_fields, sanitize_list, sanitize_text  # type: ignore

class MailControlError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class CredentialProvider(Protocol):
    def get_credential(self, account_id: str, field: str) -> str: ...

    def get_auth_bundle(self, account_id: str) -> dict[str, str]: ...

    def get_crypto_bundle(
        self, account_id: str, key_ref: str = "default"
    ) -> dict[str, str]: ...


class EnvCredentialProvider:
    def __init__(self, prefix: str = "MAIL_ACCOUNT_"):
        self.prefix = prefix

    def _name(self, account_id: str, field: str) -> str:
        safe_account = sanitize_text(account_id, 64).upper().replace("-", "_")
        safe_field = sanitize_text(field, 64).upper().replace("-", "_")
        return f"{self.prefix}{safe_account}_{safe_field}"

    def get_credential(self, account_id: str, field: str) -> str:
        import os

        direct = os.getenv(self._name(account_id, field))
        if direct:
            return direct
        shared = os.getenv(f"MAIL_SHARED_{sanitize_text(field, 64).upper()}")
        if shared:
            return shared
        raise MailControlError(
            "CREDENTIAL_NOT_FOUND",
            f"Credential not found for account '{account_id}' field '{field}'.",
        )

    def get_auth_bundle(self, account_id: str) -> dict[str, str]:
        username = self.get_credential(account_id, "username")
        password = self.get_credential(account_id, "password")
        return {"username": username, "password": password}

    def _resolve_secret(
        self, account_id: str, field: str, key_ref: str = "default"
    ) -> str:
        import os

        normalized_ref = sanitize_text(key_ref, 64).upper().replace("-", "_")
        if normalized_ref and normalized_ref != "DEFAULT":
            direct = os.getenv(self._name(account_id, f"{field}_{normalized_ref}"))
            if direct:
                return direct
        direct = os.getenv(self._name(account_id, field))
        if direct:
            return direct
        if normalized_ref and normalized_ref != "DEFAULT":
            shared = os.getenv(
                f"MAIL_SHARED_{sanitize_text(field, 64).upper()}_{normalized_ref}"
            )
            if shared:
                return shared
        shared = os.getenv(f"MAIL_SHARED_{sanitize_text(field, 64).upper()}")
        if shared:
            return shared
        raise MailControlError(
            "KEY_MATERIAL_NOT_FOUND",
            f"Missing key material for account '{account_id}' field '{field}'.",
        )

    def get_crypto_bundle(
        self, account_id: str, key_ref: str = "default"
    ) -> dict[str, str]:
        out: dict[str, str] = {}
        for key in (
            "psk",
            "password_secret",
            "openpgp_public_key",
            "openpgp_private_key",
            "openpgp_passphrase",
        ):
            try:
                out[key] = self._resolve_secret(account_id, key, key_ref=key_ref)
            except MailControlError:
                continue
        return out


class ConfirmationStore:
    def __init__(self) -> None:
        self._tokens: dict[str, dict[str, Any]] = {}

    def issue(
        self, account_id: str, action: str, scope_hash: str, ttl_seconds: int = 300
    ) -> dict[str, Any]:
        token = uuid.uuid4().hex
        now = int(time.time())
        record = {
            "account_id": account_id,
            "action": action,
            "scope_hash": scope_hash,
            "issued_at": now,
            "expires_at": now + ttl_seconds,
            "used": False,
        }
        self._tokens[token] = record
        return {"token": token, **record}

    def consume(
        self, token: str, account_id: str, action: str, scope_hash: str
    ) -> None:
        now = int(time.time())
        record = self._tokens.get(token)
        if not isinstance(record, dict):
            raise MailControlError(
                "CONFIRMATION_INVALID", "Confirmation token is invalid."
            )
        if record["used"]:
            raise MailControlError(
                "CONFIRMATION_REPLAY_BLOCKED", "Confirmation token already used."
            )
        if now > int(record["expires_at"]):
            raise MailControlError(
                "CONFIRMATION_EXPIRED", "Confirmation token expired."
            )
        if (
            record["account_id"] != account_id
            or record["action"] != action
            or record["scope_hash"] != scope_hash
        ):
            raise MailControlError(
                "CONFIRMATION_SCOPE_MISMATCH",
                "Confirmation token does not match request scope.",
            )
        record["used"] = True


def _scope_hash(account_id: str, action: str, params: dict[str, Any]) -> str:
    stable = f"{account_id}|{action}|{repr(sorted(params.items(), key=lambda i: i[0]))}"
    return hash_text(stable, 24)


def _split_content_type(value: str) -> tuple[str, str]:
    raw = sanitize_text(value, 128).lower()
    if "/" not in raw:
        return ("application", "octet-stream")
    left, right = raw.split("/", 1)
    return (left or "application", right or "octet-stream")


def _decode_attachment_payload(raw_b64: str) -> bytes:
    try:
        return base64.b64decode(raw_b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise MailControlError(
            "ATTACHMENT_INVALID_BASE64", f"Attachment is not valid base64: {exc}"
        ) from exc


def _parse_attachment_inputs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    attachments_raw = payload.get("attachments", [])
    if not isinstance(attachments_raw, list):
        return []
    max_count = clamp_int(payload.get("max_attachment_count"), 20, 0, 100)
    max_single = clamp_int(
        payload.get("max_attachment_size_bytes"),
        10 * 1024 * 1024,
        1024,
        100 * 1024 * 1024,
    )
    max_total = clamp_int(
        payload.get("max_total_attachment_bytes"),
        25 * 1024 * 1024,
        1024,
        500 * 1024 * 1024,
    )
    decoded_rows: list[dict[str, Any]] = []
    total_bytes = 0
    for index, row in enumerate(attachments_raw[:max_count]):
        if not isinstance(row, dict):
            continue
        filename = (
            sanitize_text(row.get("filename"), 256) or f"attachment-{index + 1}.bin"
        )
        content_type = (
            sanitize_text(row.get("content_type"), 128) or "application/octet-stream"
        )
        raw_b64 = sanitize_text(row.get("content_bytes_base64"), 10_000_000)
        if not raw_b64:
            continue
        decoded = _decode_attachment_payload(raw_b64)
        size = len(decoded)
        if size > max_single:
            raise MailControlError(
                "ATTACHMENT_TOO_LARGE",
                f"Attachment '{filename}' exceeds max single size.",
            )
        total_bytes += size
        if total_bytes > max_total:
            raise MailControlError(
                "ATTACHMENT_TOTAL_TOO_LARGE",
                "Total attachment payload exceeds allowed limit.",
            )
        decoded_rows.append(
            {
                "filename": filename,
                "content_type": content_type,
                "content_bytes": decoded,
                "size": size,
            }
        )
    if len(attachments_raw) > max_count:
        raise MailControlError(
            "ATTACHMENT_COUNT_EXCEEDED", "Attachment count exceeds configured limit."
        )
    return decoded_rows


def build_envelope_from_payload(payload: dict[str, Any]) -> MessageEnvelope:
    attachments_input = _parse_attachment_inputs(payload)
    attachment_items: list[AttachmentItem] = []
    for row in attachments_input:
        attachment_items.append(
            AttachmentItem(
                filename=row["filename"],
                content_type=row["content_type"],
                size=row["size"],
                content_bytes_base64=base64.b64encode(row["content_bytes"]).decode("utf-8"),
            )
        )
    headers = {
        "from": sanitize_text(payload.get("from"), 256),
        "to": ", ".join(sanitize_list(payload.get("to", []), 256, 100))
        if isinstance(payload.get("to"), list)
        else sanitize_text(payload.get("to"), 256),
        "cc": ", ".join(sanitize_list(payload.get("cc", []), 256, 100)),
        "subject": sanitize_text(payload.get("subject"), 512),
    }
    return MessageEnvelope(
        headers=headers,
        text_plain=sanitize_text(payload.get("body"), 400000),
        text_html=sanitize_text(payload.get("body_html"), 800000),
        attachments=attachment_items,
    )


def extract_encrypted_blob(message_data: dict[str, Any]) -> dict[str, Any]:
    raw_body = sanitize_text(message_data.get("body"), 2_000_000)
    if not raw_body:
        raise MailControlError("DECRYPTION_FAILED", "Message body does not contain encrypted payload.")
    try:
        parsed = json.loads(raw_body)
    except Exception as exc:  # noqa: BLE001
        raise MailControlError("DECRYPTION_FAILED", f"Encrypted payload is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise MailControlError("DECRYPTION_FAILED", "Encrypted payload must be a JSON object.")
    if "mode" not in parsed:
        raise MailControlError("DECRYPTION_FAILED", "Encrypted payload missing mode.")
    return parsed


class SmtpAdapter:
    def __init__(self, timeout_seconds: int = 20):
        self.timeout_seconds = timeout_seconds

    def verify_connectivity(
        self, account: AccountConfig, creds: dict[str, str]
    ) -> dict[str, Any]:
        mode = sanitize_text(account.smtp_tls_mode, 16).lower() or "starttls"
        if mode == "ssl":
            with smtplib.SMTP_SSL(
                account.smtp_host, account.smtp_port, timeout=self.timeout_seconds
            ) as client:
                client.login(creds["username"], creds["password"])
                return {"mode": "ssl", "features": list(client.esmtp_features.keys())}
        with smtplib.SMTP(
            account.smtp_host, account.smtp_port, timeout=self.timeout_seconds
        ) as client:
            client.ehlo()
            if mode == "starttls":
                ctx = ssl.create_default_context()
                code, _ = client.starttls(context=ctx)
                if code != 220:
                    raise MailControlError(
                        "TLS_NEGOTIATION_FAILED", "SMTP STARTTLS negotiation failed."
                    )
                client.ehlo()
            client.login(creds["username"], creds["password"])
            return {"mode": mode, "features": list(client.esmtp_features.keys())}

    def _send_prebuilt(
        self, account: AccountConfig, creds: dict[str, str], message: EmailMessage
    ) -> None:
        mode = sanitize_text(account.smtp_tls_mode, 16).lower() or "starttls"
        if mode == "ssl":
            with smtplib.SMTP_SSL(
                account.smtp_host, account.smtp_port, timeout=self.timeout_seconds
            ) as client:
                client.login(creds["username"], creds["password"])
                client.send_message(message)
            return
        with smtplib.SMTP(
            account.smtp_host, account.smtp_port, timeout=self.timeout_seconds
        ) as client:
            client.ehlo()
            if mode == "starttls":
                ctx = ssl.create_default_context()
                code, _ = client.starttls(context=ctx)
                if code != 220:
                    raise MailControlError(
                        "TLS_NEGOTIATION_FAILED", "SMTP STARTTLS negotiation failed."
                    )
                client.ehlo()
            client.login(creds["username"], creds["password"])
            client.send_message(message)

    def send_message(
        self, account: AccountConfig, creds: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        missing = require_fields(payload, ["from", "to", "subject"])
        if missing:
            raise MailControlError(
                "INVALID_ARGUMENT", f"Missing required fields: {', '.join(missing)}"
            )
        msg = EmailMessage()
        msg["From"] = sanitize_text(payload["from"], 256)
        to_values = (
            payload["to"] if isinstance(payload["to"], list) else [payload["to"]]
        )
        recipients = sanitize_list(to_values, 256, 100)
        if not recipients:
            raise MailControlError(
                "INVALID_ARGUMENT", "At least one recipient is required."
            )
        msg["To"] = ", ".join(recipients)
        cc_values = payload.get("cc", [])
        if cc_values:
            msg["Cc"] = ", ".join(sanitize_list(cc_values, 256, 100))
        msg["Subject"] = sanitize_text(payload["subject"], 512)
        plain_body = sanitize_text(payload.get("body"), 200000)
        html_body = sanitize_text(payload.get("body_html"), 400000)
        if plain_body:
            msg.set_content(plain_body)
        elif html_body:
            msg.set_content("HTML-only message.")
        else:
            raise MailControlError(
                "INVALID_ARGUMENT", "Either 'body' or 'body_html' is required."
            )
        if html_body:
            msg.add_alternative(html_body, subtype="html")
        parsed_attachments = _parse_attachment_inputs(payload)
        for row in parsed_attachments:
            maintype, subtype = _split_content_type(row["content_type"])
            msg.add_attachment(
                row["content_bytes"],
                maintype=maintype,
                subtype=subtype,
                filename=row["filename"],
            )
        self._send_prebuilt(account, creds, msg)
        return {"accepted": recipients, "attachment_count": len(parsed_attachments)}

    def send_encrypted_payload(
        self,
        account: AccountConfig,
        creds: dict[str, str],
        payload: dict[str, Any],
        encrypted_blob: dict[str, Any],
    ) -> dict[str, Any]:
        missing = require_fields(payload, ["from", "to", "subject"])
        if missing:
            raise MailControlError(
                "INVALID_ARGUMENT", f"Missing required fields: {', '.join(missing)}"
            )
        msg = EmailMessage()
        msg["From"] = sanitize_text(payload["from"], 256)
        to_values = (
            payload["to"] if isinstance(payload["to"], list) else [payload["to"]]
        )
        recipients = sanitize_list(to_values, 256, 100)
        if not recipients:
            raise MailControlError(
                "INVALID_ARGUMENT", "At least one recipient is required."
            )
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = sanitize_text(payload["subject"], 512)
        mode = sanitize_text(encrypted_blob.get("mode", ""), 32)
        msg["X-Localsetup-Encrypted"] = mode
        msg.set_content(json.dumps(encrypted_blob, separators=(",", ":")))
        self._send_prebuilt(account, creds, msg)
        return {"accepted": recipients, "encryption_mode": mode}
