#!/usr/bin/env python3
# Purpose: Shared typed structures for mail protocol control.
# Created: 2026-03-07
# Last updated: 2026-03-07

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MailResult:
    ok: bool
    code: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok, "code": self.code}
        if self.message:
            out["message"] = self.message
        if self.data:
            out.update(self.data)
        return out


@dataclass(slots=True)
class AccountConfig:
    account_id: str
    smtp_host: str
    smtp_port: int = 587
    smtp_tls_mode: str = "starttls"
    imap_host: str = ""
    imap_port: int = 993
    imap_tls: bool = True
    username_field: str = "username"
    password_field: str = "password"


@dataclass(slots=True)
class ActionContext:
    account_id: str
    action: str
    params: dict[str, Any]
    request_id: str
    idempotency_key: str | None = None


@dataclass(slots=True)
class AttachmentItem:
    filename: str
    content_type: str
    size: int
    content_bytes_base64: str = ""
    content_id: str = ""
    content_disposition: str = ""


@dataclass(slots=True)
class MessageEnvelope:
    headers: dict[str, str] = field(default_factory=dict)
    text_plain: str = ""
    text_html: str = ""
    attachments: list[AttachmentItem] = field(default_factory=list)

    def to_dict(self, include_attachment_content: bool = True) -> dict[str, Any]:
        attachments: list[dict[str, Any]] = []
        for item in self.attachments:
            row: dict[str, Any] = {
                "filename": item.filename,
                "content_type": item.content_type,
                "size": item.size,
                "content_id": item.content_id,
                "content_disposition": item.content_disposition,
            }
            if include_attachment_content:
                row["content_bytes_base64"] = item.content_bytes_base64
            attachments.append(row)
        return {
            "headers": dict(self.headers),
            "text_plain": self.text_plain,
            "text_html": self.text_html,
            "attachments": attachments,
        }
