#!/usr/bin/env python3
# Purpose: Orchestrate file_drop and mail ingest: decrypt, manifest check, promote, ledger.
# Created: 2026-03-09
# Last updated: 2026-03-09

from __future__ import annotations

import base64
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from agentq_transport_client.crypto_pipeline import CryptoPipelineError, unseal_to_manifest
from agentq_transport_client.file_drop import claim_to_processing, iter_candidates, move_to_processed
from agentq_transport_client.ledger import append_event, already_ingested, blob_id


def _ensure_manifest(m: dict[str, Any]) -> None:
    from agentq_transport_client.manifest_validate import validate_manifest

    validate_manifest(m)


def agentq_outer_to_manifest(envelope: dict[str, Any]) -> dict[str, Any]:
    """If decrypted mail/crypto envelope is agentq_outer, return inner manifest dict."""
    if envelope.get("mode") == "agentq_outer" and envelope.get("payload_b64"):
        raw = base64.b64decode(str(envelope["payload_b64"]), validate=True)
        m = json.loads(raw.decode("utf-8"))
        if not isinstance(m, dict):
            raise CryptoPipelineError("MANIFEST_PARSE_FAILED", "Inner payload not object.")
        return m
    if envelope.get("manifest_version") and envelope.get("from_agent_id"):
        return envelope
    raise CryptoPipelineError("MANIFEST_INVALID", "Not agentq_outer or manifest.")


def promote_manifest(
    queue_root: Path,
    manifest: dict[str, Any],
    transport_id: str,
    *,
    force: bool = False,
    operator: str = "",
    reason: str = "",
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Write manifest to inbox/.staging then atomic promote to in/<transport_id>/. Ledger."""
    queue_root = Path(queue_root)
    tid = sanitize_transport_id(transport_id)
    # Optional registry binding before idempotency skip so rejects are logged once
    if registry_path:
        from agentq_transport_client.registry import (
            RegistryError,
            assert_sender_allowed,
            load_registry_yaml,
            validate_registry,
        )

        try:
            raw = load_registry_yaml(Path(registry_path))
            validated = validate_registry(raw, require_keys_exist=False)
            assert_sender_allowed(validated, str(manifest.get("from_agent_id", "")))
        except RegistryError as e:
            append_event(
                queue_root,
                "ingest_verify_fail",
                {"code": "REGISTRY_SENDER_DENIED", "message": str(e), "blob_id": tid},
                transport_id=tid,
            )
            return {"status": "reject", "code": "REGISTRY_SENDER_DENIED", "message": str(e)}
    if not force and already_ingested(queue_root, tid):
        return {"status": "skipped", "transport_id": tid, "reason": "already_ingested"}
    try:
        _ensure_manifest(manifest)
    except CryptoPipelineError as e:
        append_event(
            queue_root,
            "ingest_verify_fail",
            {"code": e.code, "message": e.message, "blob_id": tid},
            transport_id=tid,
        )
        return {"status": "reject", "code": e.code}

    staging = queue_root / "inbox" / ".staging" / uuid.uuid4().hex
    staging.mkdir(parents=True, exist_ok=True)
    try:
        from agentq_transport_client.attachments_extract import extract_attachments_to_staging

        extract_attachments_to_staging(staging, manifest)
    except CryptoPipelineError as e:
        if e.code == "ingest_checksum_fail":
            append_event(
                queue_root,
                "ingest_checksum_fail",
                {"message": e.message, "blob_id": tid},
                transport_id=tid,
            )
        shutil.rmtree(staging, ignore_errors=True)
        return {"status": "reject", "code": e.code, "message": e.message}
    prd_name = manifest.get("prd_filename") or "ingested.prd.md"
    body = manifest.get("prd_body")
    if body:
        (staging / prd_name).write_text(str(body), encoding="utf-8")
    else:
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # Always keep manifest.json for queue_ops (ack_required, conversation_id) when prd_body exists
    if body:
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    promote_to = queue_root / "in"
    promote_to.mkdir(parents=True, exist_ok=True)
    final_dir = promote_to / tid
    if final_dir.exists() and not force:
        shutil.rmtree(staging, ignore_errors=True)
        return {"status": "skipped", "transport_id": tid, "reason": "target_exists"}
    if final_dir.exists():
        shutil.rmtree(final_dir, ignore_errors=True)
    shutil.move(str(staging), str(final_dir))

    append_event(
        queue_root,
        "ingest_forced" if force else "ingest_promote_ok",
        {
            "blob_id": tid,
            "from_agent_id": manifest.get("from_agent_id"),
            "operator": operator,
            "reason": reason,
        },
        transport_id=tid,
    )
    return {"status": "ok", "transport_id": tid, "promoted_to": str(final_dir)}


def sanitize_transport_id(tid: str) -> str:
    """Allow only safe chars for directory name."""
    out = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(tid))[:64]
    return out or "unknown"


def _quarantine_blob(
    queue_root: Path,
    sealed_path: Path,
    transport_id: str,
    *,
    code: str,
    message: str,
    event_type: str,
) -> dict[str, Any]:
    quarantine = queue_root / "inbox" / ".quarantine" / transport_id
    quarantine.mkdir(parents=True, exist_ok=True)
    if sealed_path.is_file():
        shutil.copy2(sealed_path, quarantine / sealed_path.name)
    (quarantine / "error.txt").write_text(f"{code}: {message}\n", encoding="utf-8")
    append_event(
        queue_root,
        event_type,
        {"code": code, "message": message, "blob_id": transport_id},
        transport_id=transport_id,
    )
    return {
        "status": "quarantine",
        "transport_id": transport_id,
        "code": code,
        "message": message,
        "quarantine": str(quarantine),
    }


def ingest_file_drop_blob(
    sealed_path: Path,
    *,
    queue_root: Path,
    recipient_private_armored: str,
    passphrase: str,
    sealed_extension: str,
    processing_dir: Path | None = None,
    processed_root: Path | None = None,
    force: bool = False,
    operator: str = "",
    reason: str = "",
    registry_path: Path | None = None,
    recipient_gnupghome: Path | None = None,
) -> dict[str, Any]:
    queue_root = Path(queue_root)
    tid = blob_id(sealed_path)
    if not force and already_ingested(queue_root, tid):
        return {"status": "skipped", "transport_id": tid, "reason": "already_ingested"}

    # Optional ready marker first line: sha256 <hex> must match sealed file (Part 6)
    try:
        from agentq_transport_client.file_drop import ready_marker_path, verify_ready_marker_sha256

        ready = ready_marker_path(sealed_path, sealed_extension)
        if ready.is_file():
            verify_ready_marker_sha256(sealed_path, ready)
    except ValueError as e:
        append_event(
            queue_root,
            "ingest_verify_fail",
            {"code": "READY_SHA256_MISMATCH", "message": str(e), "blob_id": tid},
            transport_id=tid,
        )
        return {"status": "reject", "code": "READY_SHA256_MISMATCH", "message": str(e)}

    armored = sealed_path.read_text(encoding="utf-8", errors="replace")
    # Strict gpg sign-then-encrypt path (spec): --strict-gpg only; avoids breaking PGPy envelopes.
    import os as _os

    _strict_gpg = getattr(ingest_file_drop_blob, "_strict_gpg", False) or (
        _os.environ.get("AGENTQ_INGEST_STRICT_GPG", "").lower() in ("1", "true", "yes")
    )
    if _strict_gpg:
        if not registry_path:
            message = "strict gpg ingest requires --registry to bind signer to from_agent_id"
            append_event(
                queue_root,
                "ingest_verify_fail",
                {"code": "STRICT_GPG_REGISTRY_REQUIRED", "message": message, "blob_id": tid},
                transport_id=tid,
            )
            return {
                "status": "reject",
                "transport_id": tid,
                "code": "STRICT_GPG_REGISTRY_REQUIRED",
                "message": message,
            }
        try:
            from agentq_transport_client.crypto_pipeline import unseal_to_manifest_strict_gpg
            from agentq_transport_client.registry import (
                RegistryError,
                agent_id_for_fingerprint,
                load_pubkey_armored_for_agent,
                load_registry_yaml,
                validate_registry,
            )

            _gpg = __import__(
                "agentq_transport_client.gpg_crypto", fromlist=["gpg_decrypt_verify_armored"]
            )
            plain, _fp0 = _gpg.gpg_decrypt_verify_armored(
                armored,
                recipient_sec_armored=recipient_private_armored,
                recipient_passphrase=passphrase or "",
                sender_pubkey_armored=None,
                recipient_gnupghome=recipient_gnupghome,
            )
            manifest = json.loads(plain.decode("utf-8"))
            if not isinstance(manifest, dict):
                raise CryptoPipelineError("MANIFEST_PARSE_FAILED", "gpg plaintext not object")
            if not registry_path:
                raise CryptoPipelineError("MANIFEST_INVALID", "strict gpg requires --registry")
            raw = load_registry_yaml(Path(registry_path))
            validated = validate_registry(raw, require_keys_exist=False)
            from_id = str(manifest.get("from_agent_id", ""))
            sender_pub = load_pubkey_armored_for_agent(validated, from_id)
            _plain2, signer_fp = unseal_to_manifest_strict_gpg(
                armored,
                recipient_private_armored,
                passphrase or "",
                sender_pub,
                recipient_gnupghome=recipient_gnupghome,
            )
            bound = agent_id_for_fingerprint(validated, signer_fp)
            if bound != from_id:
                append_event(
                    queue_root,
                    "ingest_verify_fail",
                    {
                        "code": "SIGNER_BINDING_FAIL",
                        "message": f"signer fp not bound to {from_id}",
                        "blob_id": tid,
                    },
                    transport_id=tid,
                )
                return {"status": "reject", "code": "SIGNER_BINDING_FAIL"}
            r = promote_manifest(
                queue_root,
                manifest,
                tid,
                force=force,
                operator=operator,
                reason=reason,
                registry_path=Path(registry_path),
            )
            if r.get("status") != "ok":
                return r
            proc = processed_root or (sealed_path.parent / "processed")
            proc.mkdir(parents=True, exist_ok=True)
            from agentq_transport_client.file_drop import processed_subdir_name

            ready = sealed_path.parent / (
                sealed_path.name[: -len(sealed_extension)] + ".ready"
            ) if sealed_extension and sealed_path.name.endswith(sealed_extension) else sealed_path.with_suffix(".ready")
            if sealed_path.exists():
                dest_proc = proc / processed_subdir_name(tid)
                dest_proc.mkdir(exist_ok=True)
                try:
                    shutil.move(str(sealed_path), str(dest_proc / sealed_path.name))
                    if ready.exists():
                        shutil.move(str(ready), str(dest_proc / ready.name))
                except OSError:
                    pass
            return r
        except Exception as e:
            code = str(getattr(e, "code", "STRICT_GPG_INGEST_FAILED"))
            message = str(getattr(e, "message", str(e)))
            return _quarantine_blob(
                queue_root,
                sealed_path,
                tid,
                code=code,
                message=message,
                event_type="ingest_verify_fail",
            )

    max_blob = 50 * 1024 * 1024
    if len(armored.encode("utf-8")) > max_blob:
        append_event(
            queue_root,
            "ingest_verify_fail",
            {"code": "BLOB_TOO_LARGE", "message": "armored payload exceeds cap", "blob_id": tid},
            transport_id=tid,
        )
        return {"status": "reject", "code": "BLOB_TOO_LARGE"}
    try:
        manifest = unseal_to_manifest(armored, recipient_private_armored, passphrase)
    except CryptoPipelineError as e:
        return _quarantine_blob(
            queue_root,
            sealed_path,
            tid,
            code=e.code,
            message=e.message,
            event_type="ingest_decrypt_fail",
        )

    r = promote_manifest(
        queue_root,
        manifest,
        tid,
        force=force,
        operator=operator,
        reason=reason,
        registry_path=registry_path,
    )
    if r.get("status") != "ok":
        return r

    proc = processed_root or (sealed_path.parent / "processed")
    proc.mkdir(parents=True, exist_ok=True)
    from agentq_transport_client.file_drop import processed_subdir_name

    ready = sealed_path.parent / (sealed_path.name[: -len(sealed_extension)] + ".ready") if sealed_extension and sealed_path.name.endswith(sealed_extension) else sealed_path.with_suffix(".ready")
    if sealed_path.exists():
        dest_proc = proc / processed_subdir_name(tid)
        dest_proc.mkdir(exist_ok=True)
        try:
            shutil.move(str(sealed_path), str(dest_proc / sealed_path.name))
            if ready.exists():
                shutil.move(str(ready), str(dest_proc / ready.name))
        except OSError:
            pass
    return r


def run_file_drop_poll(
    roots: list[Path],
    *,
    queue_root: Path,
    recipient_private_armored: str,
    passphrase: str,
    sealed_extension: str = ".agentq.asc",
    max_per_poll: int = 50,
    registry_path: Path | None = None,
    strict_gpg: bool = False,
    use_lockfile: bool = False,
) -> list[dict[str, Any]]:
    import time as _time

    if strict_gpg:
        ingest_file_drop_blob._strict_gpg = True  # type: ignore[attr-defined]
    results = []
    processing_dir = Path(queue_root) / "inbox" / ".processing"
    fail_streak = 0
    for sealed, _ready in iter_candidates(roots, sealed_extension):
        if len(results) >= max_per_poll:
            break
        claimed = claim_to_processing(
            sealed, processing_dir, sealed_extension, use_lockfile=use_lockfile
        )
        if not claimed:
            continue
        sealed_in_proc = None
        for f in claimed.iterdir():
            if f.name.endswith(sealed_extension):
                sealed_in_proc = f
                break
        if not sealed_in_proc:
            shutil.rmtree(claimed, ignore_errors=True)
            continue
        r = ingest_file_drop_blob(
            sealed_in_proc,
            queue_root=queue_root,
            recipient_private_armored=recipient_private_armored,
            passphrase=passphrase,
            sealed_extension=sealed_extension,
            processed_root=sealed.parent / "processed",
            registry_path=registry_path,
        )
        if r.get("status") == "ok":
            fail_streak = 0
            move_to_processed(claimed, sealed.parent / "processed")
        else:
            fail_streak += 1
            if fail_streak > 2:
                _time.sleep(min(2 ** min(fail_streak, 6), 60))
        results.append(r)
    return results
