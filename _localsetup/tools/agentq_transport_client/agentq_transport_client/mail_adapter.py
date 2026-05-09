#!/usr/bin/env python3
# Purpose: Mail adapter: policy-gated query UNSEEN, get_decrypted, promote, move to processed.
# Created: 2026-03-09
# Last updated: 2026-03-09

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_ENGINE = Path(__file__).resolve().parents[3]
_MAIL_SCRIPTS = _ENGINE / "skills" / "ls-mail-protocol-control" / "scripts"


def _mail_controller(policy_path: Path, accounts_path: Path) -> Any:
    sys.path.insert(0, str(_MAIL_SCRIPTS))
    from mail_protocol_control import EnvCredentialProvider, MailProtocolControl  # type: ignore
    from mail_types import AccountConfig  # type: ignore
    from mail_utils import sanitize_text  # type: ignore

    def _load_accounts(path: Path) -> list:
        if not path.is_file():
            raise FileNotFoundError(f"Accounts file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, list):
            raise ValueError("Accounts file root must be a list.")
        accounts = []
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
                )
            )
        if not accounts:
            raise ValueError("No valid account definitions found.")
        return accounts

    return MailProtocolControl(
        policy_path=policy_path,
        accounts=_load_accounts(accounts_path),
        credential_provider=EnvCredentialProvider(),
    )


def mail_pull_and_promote(
    *,
    queue_root: Path,
    account_id: str,
    policy_path: Path,
    accounts_path: Path,
    mailbox: str = "INBOX",
    post_ingest_mailbox: str = "LocalsetupAgentQ/Processed",
    query: str = "UNSEEN",
    lim: int = 25,
    confirm_token: str = "",
    registry_path: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Query messages; for each UID get_decrypted; if envelope is agentq_outer promote to in/.
    Then move_messages to post_ingest_mailbox (may require confirm_token per policy).
    """
    from agentq_transport_client.ingest import agentq_outer_to_manifest, promote_manifest

    ctrl = _mail_controller(policy_path, accounts_path)
    out: list[dict[str, Any]] = []

    queried = ctrl.dispatch(
        "mail_query",
        {"acct": account_id, "mailbox": mailbox, "query": query, "lim": lim},
    )
    if not queried.get("ok"):
        return [{"status": "error", "code": queried.get("code"), "message": queried.get("message")}]
    items = queried.get("items") or []
    for item in items:
        uid = item.get("id") if isinstance(item, dict) else None
        if not uid:
            continue
        got = ctrl.dispatch(
            "mail_get_decrypted",
            {
                "acct": account_id,
                "mailbox": mailbox,
                "id": uid,
                "encryption_mode": "openpgp",
            },
        )
        if not got.get("ok"):
            out.append(
                {"status": "skip", "uid": uid, "code": got.get("code"), "message": got.get("message")}
            )
            continue
        data = got.get("data") or {}
        decrypted = data.get("decrypted") or {}
        envelope = decrypted.get("envelope")
        if not isinstance(envelope, dict):
            out.append({"status": "skip", "uid": uid, "reason": "no_envelope"})
            continue
        # Strict gpg outer: decrypt_openpgp returns manifest dict directly (no agentq_outer wrapper)
        if envelope.get("manifest_version") and envelope.get("from_agent_id"):
            manifest = envelope
        else:
            try:
                manifest = agentq_outer_to_manifest(envelope)
            except Exception as exc:
                out.append({"status": "skip", "uid": uid, "reason": str(exc)})
                continue
        r = promote_manifest(
            queue_root, manifest, f"mail-{uid}", registry_path=registry_path
        )
        out.append({"status": r.get("status"), "uid": uid, **r})
        if r.get("status") == "ok":
            moved = ctrl.dispatch(
                "mail_mutate",
                {
                    "acct": account_id,
                    "mailbox": mailbox,
                    "mutate_action": "move_messages",
                    "uids": [uid],
                    "target_mailbox": post_ingest_mailbox,
                    "count": 1,
                    "confirm_token": confirm_token,
                },
            )
            if not moved.get("ok") and moved.get("code") == "CONFIRMATION_REQUIRED":
                out[-1]["move_pending"] = True
                out[-1]["move_message"] = moved.get("message")
            elif moved.get("ok"):
                out[-1]["moved_to"] = post_ingest_mailbox
            else:
                out[-1]["move_error"] = moved.get("code") or moved.get("message")
                # Ledger for retry (Part 13 pending_processed_move)
                try:
                    from agentq_transport_client.ledger import append_event

                    append_event(
                        queue_root,
                        "pending_processed_move",
                        {
                            "uid": uid,
                            "mailbox": mailbox,
                            "target_mailbox": post_ingest_mailbox,
                            "code": moved.get("code"),
                            "message": moved.get("message"),
                            "transport_id": f"mail-{uid}",
                        },
                        transport_id=f"mail-{uid}",
                    )
                except OSError:
                    pass

    return out


def mail_retry_pending_moves(
    *,
    queue_root: Path,
    account_id: str,
    policy_path: Path,
    accounts_path: Path,
    confirm_token: str = "",
) -> list[dict[str, Any]]:
    """
    Re-read ingest ledger for pending_processed_move; retry mail_mutate per uid.
    Appends ingest_promote_ok is wrong - append mail_move_ok or second pending if still failing.
    """
    from agentq_transport_client.ledger import append_event, pending_processed_moves

    moves = pending_processed_moves(queue_root)
    # Dedupe by uid keep last
    by_uid: dict[str, dict[str, Any]] = {}
    for rec in moves:
        uid = rec.get("uid")
        if uid is not None:
            by_uid[str(uid)] = rec
    ctrl = _mail_controller(policy_path, accounts_path)
    out: list[dict[str, Any]] = []
    for uid_str, rec in by_uid.items():
        uid = int(uid_str) if uid_str.isdigit() else uid_str
        mailbox = rec.get("mailbox") or "INBOX"
        target = rec.get("target_mailbox") or "LocalsetupAgentQ/Processed"
        moved = ctrl.dispatch(
            "mail_mutate",
            {
                "acct": account_id,
                "mailbox": mailbox,
                "mutate_action": "move_messages",
                "uids": [uid],
                "target_mailbox": target,
                "count": 1,
                "confirm_token": confirm_token,
            },
        )
        entry = {"uid": uid, "ok": moved.get("ok"), "code": moved.get("code")}
        if moved.get("ok"):
            append_event(
                queue_root,
                "mail_move_ok",
                {"uid": uid, "target_mailbox": target, "transport_id": f"mail-{uid}"},
                transport_id=f"mail-{uid}",
            )
        else:
            append_event(
                queue_root,
                "pending_processed_move",
                {
                    "uid": uid,
                    "mailbox": mailbox,
                    "target_mailbox": target,
                    "code": moved.get("code"),
                    "message": moved.get("message"),
                    "transport_id": f"mail-{uid}",
                    "retry": True,
                },
                transport_id=f"mail-{uid}",
            )
        out.append(entry)
    return out


def mail_ship_agentq_outer(
    *,
    account_id: str,
    policy_path: Path,
    accounts_path: Path,
    manifest: dict[str, Any],
    to_addr: str,
    subject: str,
    from_addr: str,
    queue_root: Path | None = None,
    skip_pre_ship: bool = False,
    pre_ship_cwd: Path | None = None,
) -> dict[str, Any]:
    """
    Build agentq_outer from manifest (same as file_drop seal inner), encrypt openpgp, send_encrypted.
    Caller must set env so account's openpgp_public_key is recipient pubkey.
    """
    from agentq_transport_client.crypto_pipeline import CryptoPipelineError
    from agentq_transport_client.ledger import append_ship_event
    from agentq_transport_client.manifest_validate import validate_manifest
    from agentq_transport_client.preship import run_pre_ship_checks

    try:
        validate_manifest(manifest)
    except CryptoPipelineError as e:
        if queue_root:
            append_ship_event(
                Path(queue_root),
                "ship_mail_fail",
                {"code": e.code, "message": e.message},
            )
        return {"ok": False, "code": e.code, "message": e.message}
    if not skip_pre_ship and not manifest.get("skip_pre_ship_checks"):
        preship = run_pre_ship_checks(manifest, cwd=pre_ship_cwd)
        if not preship.get("ok"):
            if queue_root:
                append_ship_event(
                    Path(queue_root), "ship_mail_fail", {"code": "PRE_SHIP_FAILED"}
                )
            return {"ok": False, "code": "PRE_SHIP_FAILED", "detail": preship}

    import base64

    inner = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    envelope = {
        "mode": "agentq_outer",
        "payload_b64": base64.b64encode(inner).decode("ascii"),
    }
    ctrl = _mail_controller(policy_path, accounts_path)
    result = ctrl.dispatch(
        "mail_send_encrypted",
        {
            "acct": account_id,
            "encryption_mode": "openpgp",
            "envelope": envelope,
            "from": from_addr,
            "to": [to_addr],
            "subject": subject,
        },
    )
    if queue_root:
        if result.get("ok"):
            append_ship_event(
                Path(queue_root),
                "ship_mail_ok",
                {"account_id": account_id, "to": to_addr},
            )
        else:
            append_ship_event(
                Path(queue_root),
                "ship_mail_fail",
                {"code": result.get("code"), "message": result.get("message")},
            )
    return result


def mail_ship_strict_gpg(
    *,
    account_id: str,
    policy_path: Path,
    accounts_path: Path,
    manifest: dict[str, Any],
    to_addr: str,
    subject: str,
    from_addr: str,
    recipient_pubkey_armored: str,
    signer_gnupghome: Path,
    signer_uid: str = "",
    signer_passphrase: str = "",
    queue_root: Path | None = None,
    skip_pre_ship: bool = False,
    pre_ship_cwd: Path | None = None,
) -> dict[str, Any]:
    """
    Gpg sign-then-encrypt manifest JSON; send via preencrypted_openpgp_armored.
    Pull path: mail_get_decrypted + decrypt_openpgp must return dict (PGPy decrypt of gpg blob).
    """
    from agentq_transport_client.crypto_pipeline import (
        CryptoPipelineError,
        seal_bytes_strict_gpg,
    )
    from agentq_transport_client.ledger import append_ship_event
    from agentq_transport_client.manifest_validate import validate_manifest
    from agentq_transport_client.preship import run_pre_ship_checks

    try:
        validate_manifest(manifest)
    except CryptoPipelineError as e:
        if queue_root:
            append_ship_event(
                Path(queue_root), "ship_mail_fail", {"code": e.code, "message": e.message}
            )
        return {"ok": False, "code": e.code, "message": e.message}
    if not skip_pre_ship and not manifest.get("skip_pre_ship_checks"):
        preship = run_pre_ship_checks(manifest, cwd=pre_ship_cwd)
        if not preship.get("ok"):
            if queue_root:
                append_ship_event(
                    Path(queue_root), "ship_mail_fail", {"code": "PRE_SHIP_FAILED"}
                )
            return {"ok": False, "code": "PRE_SHIP_FAILED", "detail": preship}

    inner = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    armored = seal_bytes_strict_gpg(
        inner,
        recipient_pubkey_armored,
        Path(signer_gnupghome),
        signer_uid=signer_uid or "",
        passphrase=signer_passphrase or "",
    )
    ctrl = _mail_controller(policy_path, accounts_path)
    result = ctrl.dispatch(
        "mail_send_encrypted",
        {
            "acct": account_id,
            "encryption_mode": "openpgp",
            "preencrypted_openpgp_armored": armored,
            "from": from_addr,
            "to": [to_addr],
            "subject": subject,
        },
    )
    if queue_root:
        if result.get("ok"):
            append_ship_event(
                Path(queue_root),
                "ship_mail_ok",
                {"account_id": account_id, "to": to_addr, "strict_gpg": True},
            )
        else:
            append_ship_event(
                Path(queue_root),
                "ship_mail_fail",
                {"code": result.get("code"), "message": result.get("message")},
            )
    return result
