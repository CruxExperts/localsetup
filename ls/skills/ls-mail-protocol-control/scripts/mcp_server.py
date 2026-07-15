#!/usr/bin/env python3
# Purpose: MCP-oriented bridge for mail protocol control tooling.
# Created: 2026-03-07
# Last updated: 2026-03-07

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mail_protocol_control import EnvCredentialProvider, MailProtocolControl  # type: ignore
    from mail_types import AccountConfig  # type: ignore
    from mail_utils import as_bool, sanitize_text  # type: ignore
else:
    from .mail_protocol_control import EnvCredentialProvider, MailProtocolControl
    from .mail_types import AccountConfig
    from .mail_utils import as_bool, sanitize_text


class BootstrapError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _parse_args_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BootstrapError(
            "ARGS_JSON_INVALID_JSON", f"Invalid args JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise BootstrapError(
            "ARGS_JSON_INVALID_ROOT", "args-json must decode to a JSON object."
        )
    return payload


def _parse_port(value: Any, default: int, field_name: str, row_number: int) -> int:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise BootstrapError(
            "ACCOUNT_CONFIG_INVALID_FIELD",
            f"Account row {row_number} field '{field_name}' must be an integer port.",
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise BootstrapError(
            "ACCOUNT_CONFIG_INVALID_FIELD",
            f"Account row {row_number} field '{field_name}' must be an integer port.",
        ) from exc
    if not 1 <= parsed <= 65535:
        message = (
            f"Account row {row_number} field '{field_name}' must be "
            "between 1 and 65535."
        )
        raise BootstrapError(
            "ACCOUNT_CONFIG_INVALID_FIELD",
            message,
        )
    return parsed


def _load_accounts(path: Path) -> list[AccountConfig]:
    if not path.is_file():
        raise BootstrapError(
            "ACCOUNT_CONFIG_NOT_FOUND", f"Accounts file not found: {path}"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise BootstrapError(
            "ACCOUNT_CONFIG_INVALID_JSON", f"Invalid accounts JSON: {exc}"
        ) from exc
    if not isinstance(data, list):
        raise BootstrapError(
            "ACCOUNT_CONFIG_INVALID_ROOT", "Accounts file root must be a list."
        )
    accounts: list[AccountConfig] = []
    seen_account_ids: set[str] = set()
    for index, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            raise BootstrapError(
                "ACCOUNT_CONFIG_INVALID_ENTRY",
                f"Account row {index} must be a JSON object.",
            )
        account_id = sanitize_text(row.get("account_id"), 64)
        smtp_host = sanitize_text(row.get("smtp_host"), 256)
        imap_host = sanitize_text(row.get("imap_host"), 256)
        if not account_id or not smtp_host or not imap_host:
            raise BootstrapError(
                "ACCOUNT_CONFIG_INVALID_ENTRY",
                f"Account row {index} requires account_id, smtp_host, and imap_host.",
            )
        if account_id in seen_account_ids:
            raise BootstrapError(
                "ACCOUNT_CONFIG_DUPLICATE_ACCOUNT",
                f"Duplicate account_id in accounts file: {account_id}",
            )
        seen_account_ids.add(account_id)
        accounts.append(
            AccountConfig(
                account_id=account_id,
                smtp_host=smtp_host,
                smtp_port=_parse_port(row.get("smtp_port"), 587, "smtp_port", index),
                smtp_tls_mode=sanitize_text(
                    row.get("smtp_tls_mode", "starttls"), 16
                ),
                imap_host=imap_host,
                imap_port=_parse_port(row.get("imap_port"), 993, "imap_port", index),
                imap_tls=as_bool(row.get("imap_tls"), True),
                username_field=sanitize_text(
                    row.get("username_field", "username"), 64
                ),
                password_field=sanitize_text(
                    row.get("password_field", "password"), 64
                ),
            )
        )
    if not accounts:
        raise BootstrapError(
            "ACCOUNT_CONFIG_EMPTY", "No valid account definitions found."
        )
    return accounts


class MailMcpServer:
    def __init__(self, policy_path: Path, accounts_path: Path):
        self.controller = MailProtocolControl(
            policy_path=policy_path,
            accounts=_load_accounts(accounts_path),
            credential_provider=EnvCredentialProvider(),
        )

    def call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None
    ) -> dict[str, Any]:
        payload = arguments if isinstance(arguments, dict) else {}
        return self.controller.dispatch(tool_name, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mail protocol MCP bridge")
    parser.add_argument(
        "--policy", default="ls/config/mail_protocol_policy.yaml"
    )
    parser.add_argument("--accounts", default="ls/config/mail_accounts.json")
    parser.add_argument("--tool", required=True, help="Tool name to execute")
    parser.add_argument(
        "--args-json", default="{}", help="JSON object for tool arguments"
    )
    args = parser.parse_args()
    try:
        payload = _parse_args_json(args.args_json)
        server = MailMcpServer(Path(args.policy), Path(args.accounts))
        result = server.call_tool(args.tool, payload)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    except BootstrapError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "message": exc.message}))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {"ok": False, "code": "BOOTSTRAP_ERROR", "message": str(exc)}
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
