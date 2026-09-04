#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_NAME = "ls-ui-browser-debugging"
SCHEMA_VERSION = 3
DEFAULT_TOOL = "chrome-devtools"
DEFAULT_PROFILE_RELATIVE = ".localsetup-maint/ui-browser-profiles/chrome-devtools"
SESSION_ROOT = ".localsetup-maint/ui-browser-sessions"
SESSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
PAGE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
CONTROL_CHARS = frozenset(chr(value) for value in range(0, 32)) | {chr(127)}


class SessionGuardError(ValueError):
    """Raised when a browser session record cannot be safely read or written."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _has_control_chars(value: str) -> bool:
    return any(char in CONTROL_CHARS for char in value)


def sanitize_text(name: str, value: str, *, max_length: int = 512) -> str:
    clean = value.strip()
    if not clean:
        raise SessionGuardError(f"{name} is required.")
    if _has_control_chars(clean):
        raise SessionGuardError(f"{name} contains control characters.")
    if len(clean) > max_length:
        raise SessionGuardError(f"{name} must be {max_length} characters or fewer.")
    return clean


def validate_session_id(value: str) -> str:
    session_id = sanitize_text("session-id", value, max_length=128)
    if not SESSION_ID_RE.fullmatch(session_id) or ".." in session_id:
        raise SessionGuardError("session-id must be a safe file token using letters, numbers, dot, dash, or underscore.")
    return session_id


def validate_page_id(value: str) -> str:
    page_id = sanitize_text("page-id", str(value), max_length=128)
    if not PAGE_ID_RE.fullmatch(page_id) or ".." in page_id:
        raise SessionGuardError("page-id must be a safe token using letters, numbers, dot, dash, underscore, or colon.")
    return page_id


def validate_mode(value: str) -> str:
    mode = sanitize_text("mode", value, max_length=32)
    if mode not in {"isolated", "persistent"}:
        raise SessionGuardError("mode must be isolated or persistent.")
    return mode


def validate_tool(value: str) -> str:
    tool = sanitize_text("tool", value, max_length=64)
    if tool != DEFAULT_TOOL:
        raise SessionGuardError("only chrome-devtools browser session records are supported.")
    return tool


def validate_status(value: str) -> str:
    status = sanitize_text("status", value, max_length=32)
    if status not in {"active", "needs_cleanup", "finished"}:
        raise SessionGuardError("status must be active, needs_cleanup, or finished.")
    return status


def validate_bool(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise SessionGuardError(f"{name} must be a JSON boolean.")


def normalize_state_root(value: Any) -> str:
    root = repo_root() if value is None else Path(str(value)).expanduser()
    if not root.is_absolute():
        raise SessionGuardError("state_root must be an absolute path.")
    return str(root.resolve())


def session_root(state_root: str | Path | None = None) -> Path:
    return Path(normalize_state_root(state_root)) / SESSION_ROOT


def normalize_profile_dir(value: Any, mode: str, state_root: str) -> str | None:
    if mode == "isolated":
        if value is not None:
            raise SessionGuardError("isolated sessions must not carry profile_dir.")
        return None

    profile_root = (Path(state_root) / ".localsetup-maint/ui-browser-profiles").resolve()
    expected = (Path(state_root) / DEFAULT_PROFILE_RELATIVE).resolve()
    if value is None:
        return str(expected)
    raw = sanitize_text("profile_dir", str(value), max_length=2048)
    candidate = (Path(state_root) / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    allowed = candidate == expected
    if not allowed:
        try:
            candidate.relative_to(profile_root)
            allowed = True
        except ValueError:
            allowed = False
    if not allowed:
        raise SessionGuardError(f"profile_dir must resolve to the dedicated profile under state_root: {expected}")
    return str(candidate)


def normalize_mcp_session_id(value: Any, mode: str) -> str | None:
    if mode == "persistent":
        if value is not None:
            raise SessionGuardError("persistent sessions must not carry mcp_session_id.")
        return None
    if value is None:
        return None
    return validate_session_id(str(value))


def page_ownership(page: dict[str, Any]) -> bool:
    has_owned = "owned" in page
    has_may_close = "may_close" in page
    if has_owned:
        owned = validate_bool("page owned", page["owned"])
        if has_may_close:
            may_close = validate_bool("page may_close", page["may_close"])
            if may_close != owned:
                raise SessionGuardError("page owned and may_close values must match.")
        return owned
    if has_may_close:
        return validate_bool("page may_close", page["may_close"])
    return False


def session_path(session_id: str, state_root: str | Path | None = None) -> Path:
    safe_id = validate_session_id(session_id)
    return session_root(state_root) / f"{safe_id}.json"


def profile_dir_for_mode(mode: str, state_root: str) -> str | None:
    if mode == "persistent":
        return str((Path(state_root) / DEFAULT_PROFILE_RELATIVE).resolve())
    return None


def generate_session_id(owner: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", owner.lower()).strip("-")[:32] or "agent"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return validate_session_id(f"{stamp}-{slug}-{os.getpid()}")


def _page_id_from_record(page: dict[str, Any]) -> str:
    raw_page_id = page.get("page_id", page.get("pageId"))
    if raw_page_id is None:
        raise SessionGuardError("page record is missing page_id.")
    return validate_page_id(str(raw_page_id))


def normalize_page(page: dict[str, Any], default_owner: str) -> dict[str, Any]:
    page_id = _page_id_from_record(page)
    status = str(page.get("status") or "open")
    if status not in {"open", "closed"}:
        status = "open"
    owned = page_ownership(page)
    return {
        "page_id": page_id,
        "url": sanitize_text("page url", str(page.get("url") or "unknown"), max_length=2048),
        "purpose": sanitize_text("page purpose", str(page.get("purpose") or "unspecified"), max_length=256),
        "owner": sanitize_text("page owner", str(page.get("owner") or default_owner), max_length=128),
        "owned": owned,
        "may_close": owned,
        "status": status,
    }


def upgrade_record(
    record: dict[str, Any], expected_session_id: str, expected_state_root: str | Path | None = None
) -> dict[str, Any]:
    session_id = validate_session_id(str(record.get("session_id") or expected_session_id))
    if session_id != expected_session_id:
        raise SessionGuardError("session record id does not match the requested session-id.")

    mode = record.get("mode")
    if not mode:
        mode = "persistent"
    mode = validate_mode(str(mode))

    owner = sanitize_text("owner", str(record.get("owner") or record.get("controller") or "agent"), max_length=128)
    active_page_id = record.get("active_page_id")
    normalized_pages = [normalize_page(page, owner) for page in record.get("pages", []) if isinstance(page, dict)]
    normalized_page_ids = {page["page_id"] for page in normalized_pages}
    if active_page_id is not None:
        active_page_id = validate_page_id(str(active_page_id))
        if active_page_id not in normalized_page_ids:
            active_page_id = None

    original_schema = record.get("schema_version")
    legacy = not isinstance(original_schema, int) or original_schema < SCHEMA_VERSION
    state_root = normalize_state_root(record.get("state_root") or expected_state_root)
    if expected_state_root is not None and state_root != normalize_state_root(expected_state_root):
        raise SessionGuardError("session record state_root does not match the requested state root.")
    mcp_session_id = normalize_mcp_session_id(
        record.get("mcp_session_id", session_id if mode == "isolated" and legacy else None), mode
    )
    if mode == "isolated" and mcp_session_id != session_id:
        raise SessionGuardError("isolated record mcp_session_id must be present and match session_id.")

    upgraded = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL_NAME,
        "session_id": session_id,
        "status": validate_status(str(record.get("status") or "active")),
        "mode": mode,
        "tool": validate_tool(str(record.get("tool") or record.get("mcp_server") or DEFAULT_TOOL)),
        "owner": owner,
        "purpose": sanitize_text("purpose", str(record.get("purpose") or "browser automation"), max_length=256),
        "state_root": state_root,
        "profile_dir": normalize_profile_dir(record.get("profile_dir"), mode, state_root),
        "mcp_session_id": mcp_session_id,
        "active_page_id": active_page_id,
        "pages": normalized_pages,
        "cleanup_actions": [],
    }
    upgraded["cleanup_actions"] = cleanup_actions(upgraded)
    return upgraded


def read_record(session_id: str, state_root: str | Path | None = None) -> dict[str, Any]:
    path = session_path(session_id, state_root)
    if not path.is_file():
        raise SessionGuardError(f"session record does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SessionGuardError(f"session record is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise SessionGuardError("session record must be a JSON object.")
    return upgrade_record(payload, validate_session_id(session_id), state_root)


def write_record(record: dict[str, Any], state_root: str | Path | None = None) -> dict[str, Any]:
    root = record.get("state_root") or state_root
    upgraded = upgrade_record(record, validate_session_id(str(record["session_id"])), root)
    path = session_path(upgraded["session_id"], upgraded["state_root"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(upgraded, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return upgraded


def create_record(record: dict[str, Any], state_root: str | Path | None = None) -> dict[str, Any]:
    root = record.get("state_root") or state_root
    upgraded = upgrade_record(record, validate_session_id(str(record["session_id"])), root)
    path = session_path(upgraded["session_id"], upgraded["state_root"])
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(upgraded, indent=2, sort_keys=True) + "\n")
    except FileExistsError as error:
        raise SessionGuardError(f"session record already exists: {upgraded['session_id']}") from error
    return upgraded


def open_owned_pages(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [page for page in record["pages"] if page.get("owned") and page.get("status") == "open"]


def cleanup_actions(record: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for page in open_owned_pages(record):
        actions.append(
            {
                "action": "close_page",
                "tool": str(record["tool"]),
                "page_id": str(page["page_id"]),
                "url": str(page["url"]),
                "owner": str(page["owner"]),
                "profile_dir": record.get("profile_dir"),
                "mcp_session_id": record.get("mcp_session_id"),
                "instruction": (
                    "Use Chrome DevTools MCP close_page for this owned page, then run "
                    f"browser_session_guard.py mark-closed --session-id {record['session_id']} "
                    f"--state-root {shlex.quote(record['state_root'])} "
                    f"--page-id {page['page_id']}"
                ),
            }
        )
    return actions


def start_session(
    tool: str,
    mode: str,
    owner: str,
    purpose: str,
    session_id: str | None = None,
    *,
    state_root: str | Path | None = None,
    mcp_session_id: str | None = None,
) -> dict[str, Any]:
    clean_owner = sanitize_text("owner", owner, max_length=128)
    clean_mode = validate_mode(mode)
    if clean_mode == "isolated" and session_id is None:
        raise SessionGuardError("isolated sessions require an explicit session_id assigned to that MCP server instance.")
    clean_session_id = validate_session_id(session_id) if session_id else generate_session_id(clean_owner)
    clean_state_root = normalize_state_root(state_root)
    clean_mcp_session_id = normalize_mcp_session_id(mcp_session_id, clean_mode)
    if clean_mode == "isolated" and clean_mcp_session_id is None:
        raise SessionGuardError("isolated sessions require an explicit mcp_session_id assigned to that MCP server instance.")
    if clean_mode == "isolated" and clean_mcp_session_id != clean_session_id:
        raise SessionGuardError("mcp_session_id must match session_id so active isolated actors cannot claim the same instance.")
    record = {
        "schema_version": SCHEMA_VERSION,
        "skill": SKILL_NAME,
        "session_id": clean_session_id,
        "status": "active",
        "mode": clean_mode,
        "tool": validate_tool(tool),
        "owner": clean_owner,
        "purpose": sanitize_text("purpose", purpose, max_length=256),
        "state_root": clean_state_root,
        "profile_dir": profile_dir_for_mode(clean_mode, clean_state_root),
        "mcp_session_id": clean_mcp_session_id,
        "active_page_id": None,
        "pages": [],
        "cleanup_actions": [],
    }
    return create_record(record, clean_state_root)


def _upsert_page(record: dict[str, Any], page: dict[str, Any]) -> None:
    for index, existing in enumerate(record["pages"]):
        if existing["page_id"] == page["page_id"]:
            record["pages"][index] = page
            return
    record["pages"].append(page)


def record_page(
    session_id: str,
    page_id: str,
    url: str,
    purpose: str,
    state_root: str | Path | None = None,
    page_owner: str | None = None,
) -> dict[str, Any]:
    record = read_record(session_id, state_root)
    page = normalize_page(
        {
            "page_id": page_id,
            "url": url,
            "purpose": purpose,
            "owner": page_owner or record["owner"],
            "owned": True,
            "status": "open",
        },
        record["owner"],
    )
    _upsert_page(record, page)
    record["status"] = "active"
    record["active_page_id"] = page["page_id"]
    record["cleanup_actions"] = cleanup_actions(record)
    return write_record(record)


def select_page(session_id: str, page_id: str, state_root: str | Path | None = None) -> dict[str, Any]:
    record = read_record(session_id, state_root)
    safe_page_id = validate_page_id(page_id)
    for page in record["pages"]:
        if page["page_id"] == safe_page_id and page["status"] == "open" and page["owned"]:
            record["active_page_id"] = safe_page_id
            record["cleanup_actions"] = cleanup_actions(record)
            return write_record(record)
    raise SessionGuardError(f"open owned page is not recorded: {safe_page_id}")


def mark_closed(session_id: str, page_id: str, state_root: str | Path | None = None) -> dict[str, Any]:
    record = read_record(session_id, state_root)
    safe_page_id = validate_page_id(page_id)
    for page in record["pages"]:
        if page["page_id"] == safe_page_id:
            page["status"] = "closed"
            if record.get("active_page_id") == safe_page_id:
                record["active_page_id"] = None
            record["status"] = "active"
            record["cleanup_actions"] = cleanup_actions(record)
            return write_record(record)
    raise SessionGuardError(f"page is not recorded: {safe_page_id}")


def finish_session(session_id: str, state_root: str | Path | None = None) -> tuple[dict[str, Any], int]:
    record = read_record(session_id, state_root)
    actions = cleanup_actions(record)
    record["cleanup_actions"] = actions
    if actions:
        record["status"] = "needs_cleanup"
        return write_record(record), 1
    record["status"] = "finished"
    record["active_page_id"] = None
    return write_record(record), 0


def audit_session(session_id: str, state_root: str | Path | None = None) -> dict[str, Any]:
    record = read_record(session_id, state_root)
    record["cleanup_actions"] = cleanup_actions(record)
    if record["cleanup_actions"] and record["status"] == "finished":
        record["status"] = "needs_cleanup"
    return record


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"{payload['session_id']}: {payload['status']}")
    for action in payload.get("cleanup_actions", []):
        print(f"cleanup: {action['action']} page {action['page_id']} ({action['url']})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record and audit agent-owned browser page sessions.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Create an agent-owned browser session record.")
    start_parser.add_argument("--tool", default=DEFAULT_TOOL, help="Browser MCP tool id.")
    start_parser.add_argument("--mode", choices=["isolated", "persistent"], default="isolated", help="Browser profile mode.")
    start_parser.add_argument("--owner", required=True, help="Agent or controller that owns this session.")
    start_parser.add_argument("--purpose", required=True, help="Task purpose for this browser session.")
    start_parser.add_argument("--session-id", help="Optional safe session id; generated when omitted.")
    start_parser.add_argument(
        "--state-root", required=True, help="Absolute project/state root for ownership and persistent-profile resolution."
    )
    start_parser.add_argument("--mcp-session-id", help="Required unique MCP server/session id for isolated mode.")
    start_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    record_parser = subparsers.add_parser("record-page", help="Record an agent-created browser page before use.")
    record_parser.add_argument("--session-id", required=True, help="Existing session id.")
    record_parser.add_argument("--page-id", required=True, help="Browser MCP page id.")
    record_parser.add_argument("--url", required=True, help="Current page URL.")
    record_parser.add_argument("--purpose", required=True, help="Purpose for this page.")
    record_parser.add_argument("--page-owner", help="Actor assigned to this page; defaults to the session owner.")
    record_parser.add_argument("--state-root", required=True, help="Absolute project/state root containing the session record.")
    record_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    select_parser = subparsers.add_parser("select-page", help="Mark a recorded open page as the active page.")
    select_parser.add_argument("--session-id", required=True, help="Existing session id.")
    select_parser.add_argument("--page-id", required=True, help="Recorded browser MCP page id.")
    select_parser.add_argument("--state-root", required=True, help="Absolute project/state root containing the session record.")
    select_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    closed_parser = subparsers.add_parser("mark-closed", help="Mark a recorded page closed after the MCP close action.")
    closed_parser.add_argument("--session-id", required=True, help="Existing session id.")
    closed_parser.add_argument("--page-id", required=True, help="Recorded browser MCP page id.")
    closed_parser.add_argument("--state-root", required=True, help="Absolute project/state root containing the session record.")
    closed_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    finish_parser = subparsers.add_parser("finish", help="Finish a session, failing when owned pages still need cleanup.")
    finish_parser.add_argument("--session-id", required=True, help="Existing session id.")
    finish_parser.add_argument("--state-root", required=True, help="Absolute project/state root containing the session record.")
    finish_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    audit_parser = subparsers.add_parser("audit", help="Read a session and report owned pages that still need cleanup.")
    audit_parser.add_argument("--session-id", required=True, help="Existing session id.")
    audit_parser.add_argument("--state-root", required=True, help="Absolute project/state root containing the session record.")
    audit_parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "start":
            emit(
                start_session(
                    args.tool,
                    args.mode,
                    args.owner,
                    args.purpose,
                    args.session_id,
                    state_root=args.state_root,
                    mcp_session_id=args.mcp_session_id,
                ),
                args.json,
            )
            return 0
        if args.command == "record-page":
            emit(
                record_page(
                    args.session_id,
                    args.page_id,
                    args.url,
                    args.purpose,
                    args.state_root,
                    args.page_owner,
                ),
                args.json,
            )
            return 0
        if args.command == "select-page":
            emit(select_page(args.session_id, args.page_id, args.state_root), args.json)
            return 0
        if args.command == "mark-closed":
            emit(mark_closed(args.session_id, args.page_id, args.state_root), args.json)
            return 0
        if args.command == "finish":
            payload, code = finish_session(args.session_id, args.state_root)
            emit(payload, args.json)
            return code
        if args.command == "audit":
            emit(audit_session(args.session_id, args.state_root), args.json)
            return 0
    except SessionGuardError as error:
        if getattr(args, "json", False):
            print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "error", "error": str(error)}, sort_keys=True))
        else:
            print(f"error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
