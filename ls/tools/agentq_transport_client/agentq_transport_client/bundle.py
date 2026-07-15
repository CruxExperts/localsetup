#!/usr/bin/env python3
# Purpose: Ship directory as tar.gz inside manifest attachment (size-capped).
# Created: 2026-03-10
# Last updated: 2026-03-10

"""Build manifest with one attachment content_b64 = tar.gz of directory; seal like ship_file_drop."""

from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path
from typing import Any


def tar_gz_directory(src_dir: Path) -> bytes:
    buf = io.BytesIO()
    src_dir = Path(src_dir)
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(str(src_dir), arcname=src_dir.name)
    return buf.getvalue()


def ship_bundle_file_drop(
    src_dir: Path,
    recipient_pubkey_path: Path,
    out_dir: Path,
    stem: str,
    *,
    from_agent_id: str = "local",
    max_bytes: int = 20 * 1024 * 1024,
    queue_root: Path | None = None,
    signer_gnupghome: Path | None = None,
    signer_uid: str = "",
    signer_passphrase: str = "",
    write_ready_sha256: bool = False,
) -> dict[str, Any]:
    """
    Tar+gzip src_dir; if over max_bytes return error.
    Else manifest with single attachment content_b64 + sha256; ship via ship_file_drop.
    """
    from agentq_transport_client.ship import ship_file_drop

    data = tar_gz_directory(src_dir)
    if len(data) > max_bytes:
        return {
            "status": "error",
            "code": "BUNDLE_TOO_LARGE",
            "message": f"tar.gz {len(data)} bytes > cap {max_bytes}",
        }
    sha = hashlib.sha256(data).hexdigest()
    manifest: dict[str, Any] = {
        "manifest_version": "1",
        "from_agent_id": from_agent_id,
        "prd_body": f"bundle_archive stem={stem} sha256={sha}\n",
        "prd_filename": f"{stem}.bundle.prd.md",
        "attachments": [
            {
                "path": f"{stem}.tar.gz",
                "sha256": sha,
                "bytes": len(data),
                "content_b64": base64.b64encode(data).decode("ascii"),
            }
        ],
    }
    return ship_file_drop(
        manifest,
        recipient_pubkey_path,
        out_dir,
        stem=stem,
        queue_root=queue_root,
        signer_gnupghome=signer_gnupghome,
        signer_uid=signer_uid,
        signer_passphrase=signer_passphrase,
        write_ready_sha256=write_ready_sha256,
    )
