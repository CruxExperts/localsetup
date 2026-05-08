#!/usr/bin/env python3
# Purpose: Typed structures for envelope encryption and decryption flows.
# Created: 2026-03-07
# Last updated: 2026-03-07

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class EncryptedPayload:
    mode: str
    ciphertext_b64: str
    nonce_b64: str = ""
    salt_b64: str = ""
    iterations: int = 0
    digest: str = "sha256"
    armored: str = ""
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mode": self.mode,
            "ciphertext_b64": self.ciphertext_b64,
        }
        if self.nonce_b64:
            out["nonce_b64"] = self.nonce_b64
        if self.salt_b64:
            out["salt_b64"] = self.salt_b64
        if self.iterations:
            out["iterations"] = self.iterations
        if self.digest:
            out["digest"] = self.digest
        if self.armored:
            out["armored"] = self.armored
        if isinstance(self.metadata, dict):
            out["metadata"] = dict(self.metadata)
        return out
