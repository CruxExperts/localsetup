"""Command handlers for OmniRoute admin resource operations."""

from __future__ import annotations

import argparse
from typing import Any

from .client import OmniRouteAdminClient
from .safety import require_destructive_ack
from .util import error, load_json, print_json, sanitize_path


def load_payload_file(path_raw: str) -> dict[str, Any]:
    payload = load_json(sanitize_path(path_raw))
    if not isinstance(payload, dict):
        raise ValueError("payload file must contain a JSON object")
    return payload


def confirm_single_delete(
    resource_name: str,
    resource_id: str,
    yes: bool,
    allow_destructive: bool,
) -> None:
    plan: dict[str, Any] = {
        "operations": [
            {
                "resource": resource_name,
                "action": "delete",
                "id": resource_id,
                "destructive": True,
            }
        ]
    }
    require_destructive_ack(
        plan=plan,
        confirmed=yes,
        allow_destructive=allow_destructive,
        action_name=f"delete {resource_name}",
    )


def command_provider(client: OmniRouteAdminClient, args: argparse.Namespace) -> int:
    action = args.provider_action
    if action == "list":
        print_json(client.list_providers())
        return 0
    if action == "get":
        print_json(client.get_provider(args.id))
        return 0
    if action == "create":
        print_json(client.create_provider(load_payload_file(args.payload)))
        return 0
    if action == "update":
        print_json(client.update_provider(args.id, load_payload_file(args.payload)))
        return 0
    if action == "delete":
        confirm_single_delete("provider", args.id, args.yes, args.allow_destructive)
        print_json(client.delete_provider(args.id))
        return 0
    error("Unknown provider action", details=str(action))
    return 2


def command_combo(client: OmniRouteAdminClient, args: argparse.Namespace) -> int:
    action = args.combo_action
    if action == "list":
        print_json(client.list_combos())
        return 0
    if action == "get":
        print_json(client.get_combo(args.id))
        return 0
    if action == "create":
        print_json(client.create_combo(load_payload_file(args.payload)))
        return 0
    if action == "update":
        print_json(client.update_combo(args.id, load_payload_file(args.payload)))
        return 0
    if action == "delete":
        confirm_single_delete("combo", args.id, args.yes, args.allow_destructive)
        print_json(client.delete_combo(args.id))
        return 0
    error("Unknown combo action", details=str(action))
    return 2


def command_alias(client: OmniRouteAdminClient, args: argparse.Namespace) -> int:
    action = args.alias_action
    if action == "list":
        print_json(client.list_aliases())
        return 0
    if action == "create":
        print_json(client.create_alias(load_payload_file(args.payload)))
        return 0
    if action == "update":
        print_json(client.update_alias(args.id, load_payload_file(args.payload)))
        return 0
    if action == "delete":
        confirm_single_delete("alias", args.id, args.yes, args.allow_destructive)
        print_json(client.delete_alias(args.id))
        return 0
    error("Unknown alias action", details=str(action))
    return 2


def command_budget(client: OmniRouteAdminClient, args: argparse.Namespace) -> int:
    action = args.budget_action
    if action == "get":
        print_json(client.get_budget())
        return 0
    if action == "set":
        print_json(client.set_budget(load_payload_file(args.payload)))
        return 0
    error("Unknown budget action", details=str(action))
    return 2


def command_key(client: OmniRouteAdminClient, args: argparse.Namespace) -> int:
    action = args.key_action
    if action == "list":
        print_json(client.list_keys())
        return 0
    if action == "create":
        print_json(client.create_key(load_payload_file(args.payload)))
        return 0
    if action == "delete":
        confirm_single_delete("key", args.id, args.yes, args.allow_destructive)
        print_json(client.delete_key(args.id))
        return 0
    error("Unknown key action", details=str(action))
    return 2
