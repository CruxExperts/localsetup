#!/usr/bin/env python3
# Purpose: Ship agentq_outer to file_drop (armored + ready) or via mail_send_encrypted.
# Created: 2026-03-09
# Last updated: 2026-03-09

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any


def ship_file_drop(
    manifest: dict[str, Any],
    recipient_pubkey_path: Path,
    out_dir: Path,
    stem: str = "payload",
    *,
    queue_root: Path | None = None,
    skip_pre_ship: bool = False,
    pre_ship_cwd: Path | None = None,
    signer_gnupghome: Path | None = None,
    signer_uid: str = "",
    signer_passphrase: str = "",
    write_ready_sha256: bool = False,
) -> dict[str, Any]:
    """
    Seal manifest to recipient pubkey; write <stem>.agentq.asc then <stem>.agentq.ready last.
    Optional pre_ship_checks from manifest; optional ship_log under queue_root/out.
    """
    from agentq_transport_client.crypto_pipeline import CryptoPipelineError, seal_inner_json
    from agentq_transport_client.ledger import append_ship_event
    from agentq_transport_client.manifest_validate import validate_manifest
    from agentq_transport_client.preship import run_pre_ship_checks

    try:
        validate_manifest(manifest)
    except CryptoPipelineError as e:
        if queue_root:
            append_ship_event(
                Path(queue_root),
                "ship_push_fail",
                {"code": e.code, "message": e.message, "stem": stem},
            )
        return {"status": "error", "code": e.code, "message": e.message}

    if manifest.get("skip_pre_ship_checks") and not skip_pre_ship:
        skip_pre_ship = True  # manifest documents skip
    if not skip_pre_ship:
        preship = run_pre_ship_checks(manifest, cwd=pre_ship_cwd)
        if not preship.get("ok"):
            if queue_root:
                append_ship_event(
                    Path(queue_root),
                    "ship_push_fail",
                    {"code": "PRE_SHIP_FAILED", "stem": stem, "detail": preship},
                )
            return {"status": "error", "code": "PRE_SHIP_FAILED", "detail": preship}

    pubkey = Path(recipient_pubkey_path).read_text(encoding="utf-8", errors="replace")
    if signer_gnupghome:
        from agentq_transport_client.crypto_pipeline import seal_bytes_strict_gpg

        inner = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        armored = seal_bytes_strict_gpg(
            inner,
            pubkey,
            Path(signer_gnupghome),
            signer_uid=signer_uid or "",
            passphrase=signer_passphrase or "",
        )
    else:
        armored = seal_inner_json(manifest, pubkey)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    need_bytes = len(armored.encode("utf-8")) + 65536
    try:
        du = shutil.disk_usage(out_dir)
        if du.free < need_bytes:
            if queue_root:
                append_ship_event(
                    Path(queue_root),
                    "ship_push_fail",
                    {
                        "code": "DISK_FULL",
                        "stem": stem,
                        "need_bytes": need_bytes,
                        "free_bytes": du.free,
                    },
                )
            return {
                "status": "error",
                "code": "DISK_FULL",
                "message": f"need ~{need_bytes} bytes, free {du.free}",
            }
    except OSError:
        pass

    sealed_name = f"{stem}.agentq.asc"
    ready_name = f"{stem}.agentq.ready"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=str(out_dir), prefix=".tmp_"
    ) as tf:
        tf.write(armored)
        tmp_path = Path(tf.name)
    sealed_path = out_dir / sealed_name
    tmp_path.replace(sealed_path)
    ready_path = out_dir / ready_name
    if write_ready_sha256:
        from agentq_transport_client.file_drop import sealed_file_sha256

        h = sealed_file_sha256(sealed_path)
        ready_path.write_text(f"sha256 {h}\n", encoding="utf-8")
    else:
        ready_path.write_text("", encoding="utf-8")
    # Sidecar for local archive / audit (spec Part 9)
    from datetime import datetime, timezone

    sidecar = {
        "stem": stem,
        "sealed_filename": sealed_name,
        "from_agent_id": manifest.get("from_agent_id"),
        "ts": datetime.now(timezone.utc).isoformat(),
        "manifest_version": manifest.get("manifest_version"),
    }
    (out_dir / f"{stem}.agentq.sidecar.json").write_text(
        json.dumps(sidecar, indent=2), encoding="utf-8"
    )
    if queue_root:
        append_ship_event(
            Path(queue_root),
            "ship_push_ok",
            {"stem": stem, "sealed": str(sealed_path), "from_agent_id": manifest.get("from_agent_id")},
        )
    return {"status": "ok", "sealed": str(sealed_path), "ready": str(ready_path)}


def ship_file_drop_multi(
    manifest: dict[str, Any],
    registry_path: Path,
    out_dir: Path,
    stem: str = "payload",
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """
    Multi-recipient phase 2: manifest.to_agent_ids; one sealed blob per recipient using registry pubkeys.
    """
    from agentq_transport_client.registry import load_registry_yaml, validate_registry

    ids = manifest.get("to_agent_ids")
    if not isinstance(ids, list) or not ids:
        raise ValueError("ship_file_drop_multi requires manifest.to_agent_ids non-empty")
    raw = load_registry_yaml(Path(registry_path))
    validated = validate_registry(raw, require_keys_exist=True)
    agents = validated["raw"].get("agents") or {}
    results = []
    for i, agent_id in enumerate(ids):
        cfg = agents.get(agent_id)
        if not isinstance(cfg, dict):
            results.append(
                {"status": "error", "code": "UNKNOWN_AGENT", "agent_id": agent_id}
            )
            continue
        from agentq_transport_client.registry import _collect_public_key_paths as _paths

        paths = _paths(cfg)
        if not paths or not paths[0].is_file():
            results.append(
                {"status": "error", "code": "NO_PUBKEY", "agent_id": agent_id}
            )
            continue
        r = ship_file_drop(
            manifest,
            paths[0],
            out_dir,
            stem=f"{stem}-{agent_id}",
            **kwargs,
        )
        r["agent_id"] = agent_id
        results.append(r)
    return results


def load_manifest_from_path(path: Path) -> dict[str, Any]:
    """Load JSON manifest or PRD markdown body as prd_body."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        m = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(m, dict):
            raise ValueError("JSON root must be object.")
        return m
    return {
        "manifest_version": "1",
        "from_agent_id": "local",
        "prd_body": path.read_text(encoding="utf-8", errors="replace"),
        "prd_filename": path.name,
    }
