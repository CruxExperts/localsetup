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
    from mail_utils import sanitize_text  # type: ignore
else:
    from .mail_protocol_control import EnvCredentialProvider, MailProtocolControl
    from .mail_types import AccountConfig
    from .mail_utils import sanitize_text


def _load_accounts(path: Path) -> list[AccountConfig]:
    if not path.is_file():
        raise RuntimeError(f"Accounts file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(data, list):
        raise RuntimeError("Accounts file root must be a list.")
    accounts: list[AccountConfig] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        account_id = sanitize_text(row.get("account_id"), 64)
        smtp_host = sanitize_text(row.get("smtp_host"), 256)
        imap_host = sanitize_text(row.get("imap_host"), 256)
        if not account_id or not smtp_host or not imap_host:
            continue
        accounts.append(
            AccountConfig(
                account_id=account_id,
                smtp_host=smtp_host,
                smtp_port=int(row.get("smtp_port", 587)),
                smtp_tls_mode=sanitize_text(row.get("smtp_tls_mode", "starttls"), 16),
                imap_host=imap_host,
                imap_port=int(row.get("imap_port", 993)),
                imap_tls=bool(row.get("imap_tls", True)),
                username_field=sanitize_text(row.get("username_field", "username"), 64),
                password_field=sanitize_text(row.get("password_field", "password"), 64),
            )
        )
    if not accounts:
        raise RuntimeError("No valid account definitions found.")
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
        "--policy", default="_localsetup/config/mail_protocol_policy.yaml"
    )
    parser.add_argument("--accounts", default="_localsetup/config/mail_accounts.json")
    parser.add_argument("--tool", required=True, help="Tool name to execute")
    parser.add_argument(
        "--args-json", default="{}", help="JSON object for tool arguments"
    )
    args = parser.parse_args()
    try:
        payload = json.loads(args.args_json)
        if not isinstance(payload, dict):
            raise ValueError("args-json must decode to a JSON object.")
        server = MailMcpServer(Path(args.policy), Path(args.accounts))
        result = server.call_tool(args.tool, payload)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "code": "BOOTSTRAP_ERROR", "message": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
