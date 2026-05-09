#!/usr/bin/env python3
# Purpose: Full-envelope encryption and decryption for mail payloads.
# Created: 2026-03-07
# Last updated: 2026-03-07

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
from deps import require_deps  # noqa: E402

require_deps(["cryptography"])

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
from cryptography.hazmat.primitives.kdf.hkdf import HKDF  # noqa: E402
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: E402

try:
    import pgpy  # type: ignore
except Exception:  # noqa: BLE001
    pgpy = None

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from crypto_types import EncryptedPayload  # type: ignore
else:
    from .crypto_types import EncryptedPayload


class CryptoError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class CryptoEngine:
    def __init__(self, pbkdf2_iterations: int = 390000):
        self.pbkdf2_iterations = pbkdf2_iterations

    def _serialize_envelope(self, envelope: dict[str, Any]) -> bytes:
        try:
            text = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        except Exception as exc:  # noqa: BLE001
            raise CryptoError("ENVELOPE_SERIALIZATION_FAILED", str(exc)) from exc
        return text.encode("utf-8", errors="replace")

    def _deserialize_envelope(self, payload: bytes) -> dict[str, Any]:
        try:
            decoded = json.loads(payload.decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            raise CryptoError("DECRYPTION_FAILED", str(exc)) from exc
        if not isinstance(decoded, dict):
            raise CryptoError(
                "DECRYPTION_FAILED", "Decrypted payload is not an object."
            )
        return decoded

    def _aes_encrypt(
        self, plaintext: bytes, key: bytes, salt: bytes
    ) -> EncryptedPayload:
        nonce = os.urandom(12)
        cipher = AESGCM(key)
        ciphertext = cipher.encrypt(nonce, plaintext, None)
        return EncryptedPayload(
            mode="aes-gcm",
            ciphertext_b64=base64.b64encode(ciphertext).decode("utf-8"),
            nonce_b64=base64.b64encode(nonce).decode("utf-8"),
            salt_b64=base64.b64encode(salt).decode("utf-8"),
            digest="sha256",
        )

    def _aes_decrypt(self, encrypted: dict[str, Any], key: bytes) -> bytes:
        try:
            nonce = base64.b64decode(str(encrypted["nonce_b64"]), validate=True)
            ciphertext = base64.b64decode(
                str(encrypted["ciphertext_b64"]), validate=True
            )
        except Exception as exc:  # noqa: BLE001
            raise CryptoError(
                "DECRYPTION_FAILED", f"Invalid encrypted payload encoding: {exc}"
            ) from exc
        try:
            cipher = AESGCM(key)
            return cipher.decrypt(nonce, ciphertext, None)
        except Exception as exc:  # noqa: BLE001
            raise CryptoError(
                "DECRYPTION_FAILED", f"AES-GCM decrypt failure: {exc}"
            ) from exc

    def encrypt_psk(self, envelope: dict[str, Any], psk: str) -> dict[str, Any]:
        if not psk:
            raise CryptoError("KEY_MATERIAL_NOT_FOUND", "Missing PSK material.")
        salt = os.urandom(16)
        hkdf = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=salt, info=b"localsetup-mail-psk"
        )
        key = hkdf.derive(psk.encode("utf-8", errors="replace"))
        encrypted = self._aes_encrypt(self._serialize_envelope(envelope), key, salt)
        out = encrypted.to_dict()
        out["mode"] = "psk"
        return out

    def decrypt_psk(self, encrypted: dict[str, Any], psk: str) -> dict[str, Any]:
        if not psk:
            raise CryptoError("KEY_MATERIAL_NOT_FOUND", "Missing PSK material.")
        try:
            salt = base64.b64decode(str(encrypted["salt_b64"]), validate=True)
        except Exception as exc:  # noqa: BLE001
            raise CryptoError(
                "DECRYPTION_FAILED", f"Invalid salt encoding: {exc}"
            ) from exc
        hkdf = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=salt, info=b"localsetup-mail-psk"
        )
        key = hkdf.derive(psk.encode("utf-8", errors="replace"))
        return self._deserialize_envelope(self._aes_decrypt(encrypted, key))

    def encrypt_password(
        self, envelope: dict[str, Any], password_secret: str
    ) -> dict[str, Any]:
        if not password_secret:
            raise CryptoError("KEY_MATERIAL_NOT_FOUND", "Missing password secret.")
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self.pbkdf2_iterations,
        )
        key = kdf.derive(password_secret.encode("utf-8", errors="replace"))
        encrypted = self._aes_encrypt(self._serialize_envelope(envelope), key, salt)
        out = encrypted.to_dict()
        out["mode"] = "password"
        out["iterations"] = self.pbkdf2_iterations
        return out

    def decrypt_password(
        self, encrypted: dict[str, Any], password_secret: str
    ) -> dict[str, Any]:
        if not password_secret:
            raise CryptoError("KEY_MATERIAL_NOT_FOUND", "Missing password secret.")
        try:
            salt = base64.b64decode(str(encrypted["salt_b64"]), validate=True)
        except Exception as exc:  # noqa: BLE001
            raise CryptoError(
                "DECRYPTION_FAILED", f"Invalid salt encoding: {exc}"
            ) from exc
        iterations = int(encrypted.get("iterations", self.pbkdf2_iterations))
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
        )
        key = kdf.derive(password_secret.encode("utf-8", errors="replace"))
        return self._deserialize_envelope(self._aes_decrypt(encrypted, key))

    def encrypt_openpgp(
        self, envelope: dict[str, Any], public_key_ascii: str
    ) -> dict[str, Any]:
        if pgpy is None:
            raise CryptoError(
                "ENCRYPTION_MODE_UNSUPPORTED", "OpenPGP dependency not installed."
            )
        if not public_key_ascii:
            raise CryptoError("KEY_MATERIAL_NOT_FOUND", "Missing OpenPGP public key.")
        try:
            pubkey, _ = pgpy.PGPKey.from_blob(public_key_ascii)
            msg = pgpy.PGPMessage.new(
                self._serialize_envelope(envelope).decode("utf-8", errors="replace")
            )
            encrypted_msg = pubkey.encrypt(msg)
            armored = str(encrypted_msg)
        except Exception as exc:  # noqa: BLE001
            raise CryptoError(
                "ENCRYPTION_FAILED", f"OpenPGP encrypt failure: {exc}"
            ) from exc
        return {
            "mode": "openpgp",
            "armored": armored,
            "ciphertext_b64": base64.b64encode(armored.encode("utf-8")).decode("utf-8"),
        }

    def decrypt_openpgp(
        self, encrypted: dict[str, Any], private_key_ascii: str, passphrase: str = ""
    ) -> dict[str, Any]:
        if pgpy is None:
            raise CryptoError(
                "ENCRYPTION_MODE_UNSUPPORTED", "OpenPGP dependency not installed."
            )
        if not private_key_ascii:
            raise CryptoError("KEY_MATERIAL_NOT_FOUND", "Missing OpenPGP private key.")
        armored = str(encrypted.get("armored", "")).strip()
        if not armored:
            try:
                armored = base64.b64decode(
                    str(encrypted["ciphertext_b64"]), validate=True
                ).decode("utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001
                raise CryptoError(
                    "DECRYPTION_FAILED", f"Invalid OpenPGP payload: {exc}"
                ) from exc
        try:
            privkey, _ = pgpy.PGPKey.from_blob(private_key_ascii)
            if privkey.is_protected:
                with privkey.unlock(passphrase):
                    message = pgpy.PGPMessage.from_blob(armored)
                    decrypted = privkey.decrypt(message)
            else:
                message = pgpy.PGPMessage.from_blob(armored)
                decrypted = privkey.decrypt(message)
            text = str(decrypted.message)
        except Exception as exc:  # noqa: BLE001
            raise CryptoError(
                "DECRYPTION_FAILED", f"OpenPGP decrypt failure: {exc}"
            ) from exc
        return self._deserialize_envelope(text.encode("utf-8", errors="replace"))

    def encrypt(
        self, mode: str, envelope: dict[str, Any], secrets: dict[str, str]
    ) -> dict[str, Any]:
        if mode == "psk":
            return self.encrypt_psk(envelope, secrets.get("psk", ""))
        if mode == "password":
            return self.encrypt_password(envelope, secrets.get("password_secret", ""))
        if mode == "openpgp":
            return self.encrypt_openpgp(envelope, secrets.get("openpgp_public_key", ""))
        raise CryptoError(
            "ENCRYPTION_MODE_UNSUPPORTED", f"Unsupported encryption mode: {mode}"
        )

    def decrypt(
        self, mode: str, encrypted: dict[str, Any], secrets: dict[str, str]
    ) -> dict[str, Any]:
        if mode == "psk":
            return self.decrypt_psk(encrypted, secrets.get("psk", ""))
        if mode == "password":
            return self.decrypt_password(encrypted, secrets.get("password_secret", ""))
        if mode == "openpgp":
            return self.decrypt_openpgp(
                encrypted,
                secrets.get("openpgp_private_key", ""),
                secrets.get("openpgp_passphrase", ""),
            )
        raise CryptoError(
            "ENCRYPTION_MODE_UNSUPPORTED", f"Unsupported decryption mode: {mode}"
        )
