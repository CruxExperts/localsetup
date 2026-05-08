#!/usr/bin/env python3
# Purpose: Policy-gated SMTP and IMAP control layer for delegated mail accounts.
# Created: 2026-03-07
# Last updated: 2026-03-07

from __future__ import annotations

import base64
import email
import json
import imaplib
import smtplib
import ssl
import sys
import time
import uuid
from dataclasses import asdict
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from crypto_engine import CryptoEngine, CryptoError  # type: ignore
    from mail_types import AccountConfig, AttachmentItem, MailResult, MessageEnvelope  # type: ignore
    from mail_utils import (
        as_bool,
        clamp_int,
        hash_text,
        make_request_id,
        require_fields,
        sanitize_list,
        sanitize_text,
    )  # type: ignore
    from policy_engine import PolicyError, evaluate_action, load_policy  # type: ignore
else:
    from .crypto_engine import CryptoEngine, CryptoError
    from .mail_types import AccountConfig, AttachmentItem, MailResult, MessageEnvelope
    from .mail_utils import (
        as_bool,
        clamp_int,
        hash_text,
        make_request_id,
        require_fields,
        sanitize_list,
        sanitize_text,
    )
    from .policy_engine import PolicyError, evaluate_action, load_policy


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


class ImapAdapter:
    def __init__(self, timeout_seconds: int = 30):
        self.timeout_seconds = timeout_seconds

    def _connect(self, account: AccountConfig, creds: dict[str, str]) -> imaplib.IMAP4:
        if account.imap_tls:
            client: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                account.imap_host, account.imap_port, timeout=self.timeout_seconds
            )
        else:
            client = imaplib.IMAP4(
                account.imap_host, account.imap_port, timeout=self.timeout_seconds
            )
        status, _ = client.login(creds["username"], creds["password"])
        if status != "OK":
            raise MailControlError("AUTH_FAILED", "IMAP authentication failed.")
        return client

    def _fetch_message_object(
        self, client: imaplib.IMAP4, uid: str, fetch_spec: str = "(BODY.PEEK[] FLAGS)"
    ) -> email.message.Message:
        f_status, f_data = client.uid("FETCH", uid, fetch_spec)
        if f_status != "OK" or not f_data:
            raise MailControlError("IMAP_FETCH_FAILED", f"Unable to fetch uid={uid}")
        raw = b""
        for part in f_data:
            if (
                isinstance(part, tuple)
                and len(part) > 1
                and isinstance(part[1], (bytes, bytearray))
            ):
                raw += bytes(part[1])
        return email.message_from_bytes(raw)

    def get_capabilities(
        self, account: AccountConfig, creds: dict[str, str]
    ) -> dict[str, Any]:
        with self._connect(account, creds) as client:
            caps = sorted(
                [
                    c.decode("utf-8", errors="replace")
                    for c in (client.capabilities or [])
                ]
            )
            return {"capabilities": caps}

    def list_mailboxes(
        self, account: AccountConfig, creds: dict[str, str]
    ) -> dict[str, Any]:
        with self._connect(account, creds) as client:
            status, data = client.list()
            if status != "OK":
                raise MailControlError("IMAP_LIST_FAILED", "Unable to list mailboxes.")
            boxes = [
                line.decode("utf-8", errors="replace") for line in (data or []) if line
            ]
            return {"mailboxes": boxes}

    def query_messages(
        self, account: AccountConfig, creds: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        mailbox = sanitize_text(payload.get("mailbox", "INBOX"), 128)
        query = sanitize_text(payload.get("query", "ALL"), 256)
        lim = clamp_int(payload.get("lim"), 25, 1, 100)
        offset = clamp_int(payload.get("offset"), 0, 0, 1_000_000)
        with self._connect(account, creds) as client:
            status, _ = client.select(mailbox, readonly=True)
            if status != "OK":
                raise MailControlError(
                    "IMAP_SELECT_FAILED", f"Cannot select mailbox: {mailbox}"
                )
            status, data = client.uid("SEARCH", None, query)
            if status != "OK":
                raise MailControlError("IMAP_SEARCH_FAILED", "Search failed.")
            uids = (data[0] or b"").decode("utf-8", errors="replace").split()
            window = uids[offset : offset + lim]
            items: list[dict[str, Any]] = []
            for uid in window:
                msg = self._fetch_message_object(
                    client, uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] FLAGS)"
                )
                items.append(
                    {
                        "id": uid,
                        "from": sanitize_text(msg.get("From", ""), 256),
                        "sub": sanitize_text(msg.get("Subject", ""), 256),
                        "dt": sanitize_text(msg.get("Date", ""), 128),
                    }
                )
            next_offset = offset + len(window)
            return {
                "items": items,
                "total": len(uids),
                "next": next_offset if next_offset < len(uids) else None,
            }

    def get_message(
        self, account: AccountConfig, creds: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        mailbox = sanitize_text(payload.get("mailbox", "INBOX"), 128)
        uid = sanitize_text(payload.get("id"), 64)
        detail = as_bool(payload.get("detail"), False)
        include_attachment_content = as_bool(
            payload.get("include_attachment_content"), False
        )
        max_attachment_content = clamp_int(
            payload.get("max_attachment_content_bytes"),
            1024 * 1024,
            1024,
            100 * 1024 * 1024,
        )
        if not uid:
            raise MailControlError("INVALID_ARGUMENT", "Message id is required.")
        with self._connect(account, creds) as client:
            status, _ = client.select(mailbox, readonly=True)
            if status != "OK":
                raise MailControlError(
                    "IMAP_SELECT_FAILED", f"Cannot select mailbox: {mailbox}"
                )
            fetch_spec = (
                "(BODY.PEEK[] FLAGS)"
                if detail
                else "(BODY.PEEK[HEADER] FLAGS BODYSTRUCTURE)"
            )
            msg = self._fetch_message_object(client, uid, fetch_spec=fetch_spec)
            result: dict[str, Any] = {
                "id": uid,
                "from": sanitize_text(msg.get("From", ""), 256),
                "to": sanitize_text(msg.get("To", ""), 256),
                "cc": sanitize_text(msg.get("Cc", ""), 256),
                "sub": sanitize_text(msg.get("Subject", ""), 256),
                "dt": sanitize_text(msg.get("Date", ""), 128),
            }
            attachments: list[dict[str, Any]] = []
            if detail:
                body = ""
                html_body = ""
                if msg.is_multipart():
                    for index, part in enumerate(msg.walk()):
                        if part.is_multipart():
                            continue
                        ctype = part.get_content_type()
                        disp = str(part.get("Content-Disposition", "")).lower()
                        filename = sanitize_text(part.get_filename() or "", 256)
                        payload_bytes = part.get_payload(decode=True) or b""
                        if filename or "attachment" in disp:
                            row = {
                                "attachment_index": index,
                                "filename": filename or f"attachment-{index}",
                                "content_type": ctype,
                                "size": len(payload_bytes),
                                "content_id": sanitize_text(
                                    str(part.get("Content-ID", "")), 128
                                ),
                                "content_disposition": disp,
                            }
                            if include_attachment_content:
                                if len(payload_bytes) > max_attachment_content:
                                    row["content_truncated"] = True
                                    row["content_bytes_base64"] = base64.b64encode(
                                        payload_bytes[:max_attachment_content]
                                    ).decode("utf-8")
                                else:
                                    row["content_bytes_base64"] = base64.b64encode(
                                        payload_bytes
                                    ).decode("utf-8")
                            attachments.append(row)
                            continue
                        if ctype == "text/plain":
                            body = payload_bytes.decode(errors="replace")
                        elif ctype == "text/html":
                            html_body = payload_bytes.decode(errors="replace")
                else:
                    raw_body = msg.get_payload(decode=True) or b""
                    body = raw_body.decode(errors="replace")
                    html_body = ""
                result["body"] = sanitize_text(body, 400000)
                if html_body:
                    result["body_html"] = sanitize_text(html_body, 800000)
            result["attachments"] = attachments
            return result

    def get_attachment(
        self, account: AccountConfig, creds: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        mailbox = sanitize_text(payload.get("mailbox", "INBOX"), 128)
        uid = sanitize_text(payload.get("id"), 64)
        attachment_index = clamp_int(payload.get("attachment_index"), -1, -1, 10_000)
        if not uid:
            raise MailControlError("INVALID_ARGUMENT", "Message id is required.")
        if attachment_index < 0:
            raise MailControlError("INVALID_ARGUMENT", "attachment_index is required.")
        chunk_size = clamp_int(payload.get("chunk_size"), 256 * 1024, 1024, 1024 * 1024)
        offset = clamp_int(payload.get("offset"), 0, 0, 1_000_000_000)
        with self._connect(account, creds) as client:
            status, _ = client.select(mailbox, readonly=True)
            if status != "OK":
                raise MailControlError(
                    "IMAP_SELECT_FAILED", f"Cannot select mailbox: {mailbox}"
                )
            msg = self._fetch_message_object(
                client, uid, fetch_spec="(BODY.PEEK[] FLAGS)"
            )
            candidates: list[email.message.Message] = []
            for part in msg.walk():
                if part.is_multipart():
                    continue
                disp = str(part.get("Content-Disposition", "")).lower()
                filename = part.get_filename()
                if filename or "attachment" in disp:
                    candidates.append(part)
            if attachment_index >= len(candidates):
                raise MailControlError(
                    "ATTACHMENT_NOT_FOUND", "attachment_index out of range."
                )
            target = candidates[attachment_index]
            content = target.get_payload(decode=True) or b""
            end = min(len(content), offset + chunk_size)
            chunk = content[offset:end]
            filename = sanitize_text(
                target.get_filename() or f"attachment-{attachment_index}", 256
            )
            return {
                "id": uid,
                "attachment_index": attachment_index,
                "filename": filename,
                "content_type": target.get_content_type(),
                "size": len(content),
                "offset": offset,
                "chunk_size": len(chunk),
                "content_bytes_base64": base64.b64encode(chunk).decode("utf-8"),
                "next_offset": end if end < len(content) else None,
                "done": end >= len(content),
            }

    def mutate(
        self, account: AccountConfig, creds: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        action = sanitize_text(payload.get("mutate_action"), 64)
        mailbox = sanitize_text(payload.get("mailbox", "INBOX"), 128)
        uids = sanitize_list(payload.get("uids", []), 64, 1000)
        with self._connect(account, creds) as client:
            status, _ = client.select(mailbox)
            if status != "OK":
                raise MailControlError(
                    "IMAP_SELECT_FAILED", f"Cannot select mailbox: {mailbox}"
                )
            uid_set = ",".join(uids)
            if action in {"set_flags", "clear_flags"}:
                flags = sanitize_text(payload.get("flags", "\\Seen"), 128)
                op = "+FLAGS" if action == "set_flags" else "-FLAGS"
                m_status, _ = client.uid("STORE", uid_set, op, flags)
                if m_status != "OK":
                    raise MailControlError("IMAP_STORE_FAILED", "Flag update failed.")
                return {"updated": len(uids), "action": action}
            if action == "copy_messages":
                target = sanitize_text(payload.get("target_mailbox"), 128)
                m_status, _ = client.uid("COPY", uid_set, target)
                if m_status != "OK":
                    raise MailControlError("IMAP_COPY_FAILED", "Copy failed.")
                return {"copied": len(uids), "target": target}
            if action == "move_messages":
                target = sanitize_text(payload.get("target_mailbox"), 128)
                supports_move = b"MOVE" in (client.capabilities or ())
                if supports_move:
                    m_status, _ = client.uid("MOVE", uid_set, target)
                    if m_status != "OK":
                        raise MailControlError("IMAP_MOVE_FAILED", "MOVE failed.")
                else:
                    c_status, _ = client.uid("COPY", uid_set, target)
                    if c_status != "OK":
                        raise MailControlError(
                            "IMAP_MOVE_FAILED", "MOVE fallback COPY failed."
                        )
                    s_status, _ = client.uid("STORE", uid_set, "+FLAGS", "(\\Deleted)")
                    if s_status != "OK":
                        raise MailControlError(
                            "IMAP_MOVE_FAILED", "MOVE fallback STORE failed."
                        )
                    e_status, _ = client.expunge()
                    if e_status != "OK":
                        raise MailControlError(
                            "IMAP_MOVE_FAILED", "MOVE fallback EXPUNGE failed."
                        )
                return {"moved": len(uids), "target": target}
            if action == "delete_messages":
                s_status, _ = client.uid("STORE", uid_set, "+FLAGS", "(\\Deleted)")
                if s_status != "OK":
                    raise MailControlError("IMAP_DELETE_FAILED", "Delete mark failed.")
                return {"deleted_marked": len(uids)}
            if action == "expunge_mailbox":
                e_status, _ = client.expunge()
                if e_status != "OK":
                    raise MailControlError("IMAP_EXPUNGE_FAILED", "Expunge failed.")
                return {"expunged": True}
            if action == "create_mailbox":
                target = sanitize_text(payload.get("target_mailbox"), 128)
                c_status, _ = client.create(target)
                if c_status != "OK":
                    raise MailControlError(
                        "IMAP_CREATE_FAILED", "Create mailbox failed."
                    )
                return {"created": target}
            if action == "rename_mailbox":
                src = sanitize_text(payload.get("source_mailbox"), 128)
                dst = sanitize_text(payload.get("target_mailbox"), 128)
                r_status, _ = client.rename(src, dst)
                if r_status != "OK":
                    raise MailControlError(
                        "IMAP_RENAME_FAILED", "Rename mailbox failed."
                    )
                return {"renamed": {"from": src, "to": dst}}
            if action == "delete_mailbox":
                target = sanitize_text(payload.get("target_mailbox"), 128)
                d_status, _ = client.delete(target)
                if d_status != "OK":
                    raise MailControlError(
                        "IMAP_DELETE_MAILBOX_FAILED", "Delete mailbox failed."
                    )
                return {"deleted_mailbox": target}
        raise MailControlError(
            "INVALID_ARGUMENT", f"Unsupported mutate action: {action}"
        )


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

    def _build_envelope_from_payload(self, payload: dict[str, Any]) -> MessageEnvelope:
        attachments_input = _parse_attachment_inputs(payload)
        attachment_items: list[AttachmentItem] = []
        for row in attachments_input:
            attachment_items.append(
                AttachmentItem(
                    filename=row["filename"],
                    content_type=row["content_type"],
                    size=row["size"],
                    content_bytes_base64=base64.b64encode(row["content_bytes"]).decode(
                        "utf-8"
                    ),
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

    def _extract_encrypted_blob(self, message_data: dict[str, Any]) -> dict[str, Any]:
        raw_body = sanitize_text(message_data.get("body"), 2_000_000)
        if not raw_body:
            raise MailControlError(
                "DECRYPTION_FAILED", "Message body does not contain encrypted payload."
            )
        try:
            parsed = json.loads(raw_body)
        except Exception as exc:  # noqa: BLE001
            raise MailControlError(
                "DECRYPTION_FAILED", f"Encrypted payload is not valid JSON: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise MailControlError(
                "DECRYPTION_FAILED", "Encrypted payload must be a JSON object."
            )
        if "mode" not in parsed:
            raise MailControlError(
                "DECRYPTION_FAILED", "Encrypted payload missing mode."
            )
        return parsed

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
            envelope_obj = self._build_envelope_from_payload(payload).to_dict(
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
        encrypted_blob = self._extract_encrypted_blob(message)
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
        except PolicyError as exc:
            return MailResult(ok=False, code="POLICY_ERROR", message=str(exc)).to_dict()
        except CryptoError as exc:
            return MailResult(ok=False, code=exc.code, message=exc.message).to_dict()
        except Exception as exc:  # noqa: BLE001
            return MailResult(
                ok=False, code="UNHANDLED_ERROR", message=str(exc)
            ).to_dict()
