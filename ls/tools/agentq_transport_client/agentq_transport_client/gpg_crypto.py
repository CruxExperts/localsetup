#!/usr/bin/env python3
# Purpose: GnuPG sign-then-encrypt outer blob and decrypt+verify (original spec Part 1 #5).
# Created: 2026-03-10
# Last updated: 2026-03-10

"""
Uses gpg in subprocess. Signer keyring must contain signer secret; recipient pubkey imported for -r.
Decrypt: temporary keyring with recipient secret + sender public keys for Good signature check.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class GpgCryptoError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_FINGERPRINT_RE = re.compile(
    r"Primary key fingerprint:\s*([0-9A-Fa-f ]+)", re.MULTILINE
)
_VALID_SIG_RE = re.compile(r"^\[GNUPG:\]\s+VALIDSIG\s+(\S+)", re.MULTILINE)


def _which_gpg() -> str:
    return shutil.which("gpg") or shutil.which("gpg2") or ""


def gpg_sign_encrypt_armored(
    plaintext: bytes,
    *,
    recipient_pubkey_armored: str,
    signer_gnupghome: Path,
    signer_uid: str = "",
    passphrase: str = "",
    trust_model_always: bool = True,
) -> str:
    """
    Import recipient pubkey into signer homedir temp overlay... actually import into signer homedir
    pollutes it. Use separate temp homedir: import signer sec from signer_gnupghome is hard.
    Simpler: temp homedir, import recipient pub only, then we need signer sec - export signer sec
    to temp not ideal. Alternative: signer_gnupghome is full ring; gpg --import recipient pub
    into signer ring (one extra pubkey), then gpg --sign --encrypt -r RECIP_FPR -u SIGNER.
    Caller responsible for cleaning or use dedicated agentq signer ring.
    """
    gpg = _which_gpg()
    if not gpg:
        raise GpgCryptoError("GPG_NOT_FOUND", "gpg not on PATH")

    signer_gnupghome = Path(signer_gnupghome)
    if not signer_gnupghome.is_dir():
        raise GpgCryptoError("KEYRING_NOT_FOUND", f"GNUPGHOME not a dir: {signer_gnupghome}")

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        recip_pub = t / "recipient.pub.asc"
        recip_pub.write_text(recipient_pubkey_armored, encoding="utf-8")
        plain = t / "payload.bin"
        plain.write_bytes(plaintext)
        out = t / "out.asc"
        env = {"GNUPGHOME": str(signer_gnupghome)}
        r_import = subprocess.run(
            [gpg, "--batch", "--import", str(recip_pub)],
            env={**__import__("os").environ, **env},
            capture_output=True,
            timeout=60,
        )
        if r_import.returncode != 0:
            raise GpgCryptoError(
                "IMPORT_FAILED", r_import.stderr.decode(errors="replace")[:500]
            )
        cmd = [
            gpg,
            "--batch",
            "--armor",
            "--sign",
            "--encrypt",
            "-o",
            str(out),
        ]
        if trust_model_always:
            cmd.append("--trust-model")
            cmd.append("always")
        # Recipient: use email from key if possible; else first uid - gpg -r needs key id
        cmd.extend(["-r", _recipient_key_spec(recipient_pubkey_armored)])
        if signer_uid:
            cmd.extend(["--local-user", signer_uid])
        cmd.append(str(plain))
        stdin = subprocess.DEVNULL
        if passphrase:
            cmd[1:1] = ["--pinentry-mode", "loopback", "--passphrase-fd", "0"]
            stdin = subprocess.PIPE
        r = subprocess.run(
            cmd,
            env={**__import__("os").environ, **env},
            input=(passphrase + "\n").encode() if passphrase else None,
            capture_output=True,
            timeout=120,
        )
        if r.returncode != 0:
            raise GpgCryptoError(
                "SIGN_ENCRYPT_FAILED", r.stderr.decode(errors="replace")[:800]
            )
        return out.read_text(encoding="utf-8", errors="replace")


def _recipient_key_spec(pubkey_armored: str) -> str:
    """Extract fingerprint from armored pubkey for -r."""
    try:
        import pgpy  # type: ignore

        k, _ = pgpy.PGPKey.from_blob(pubkey_armored)
        fp = str(k.fingerprint).replace(" ", "")
        return fp[-16:] if len(fp) >= 16 else fp  # gpg accepts long key id
    except Exception:
        return "recipient"  # fallback if import fails


def gpg_decrypt_verify_armored(
    armored: str,
    *,
    recipient_sec_armored: str,
    recipient_passphrase: str = "",
    sender_pubkey_armored: str | None = None,
    recipient_gnupghome: Path | str | None = None,
) -> tuple[bytes, str]:
    """
    Decrypt with recipient secret; verify signature if sender pubkey provided.
    If recipient_gnupghome is set, decrypt using that keyring (no armored import).
    Returns (plaintext_bytes, signer_fingerprint_hex_no_spaces).
    """
    gpg = _which_gpg()
    if not gpg:
        raise GpgCryptoError("GPG_NOT_FOUND", "gpg not on PATH")

    home = Path(recipient_gnupghome) if recipient_gnupghome else None
    tmp_ctx = None
    if home is None or not home.is_dir():
        tmp_ctx = tempfile.TemporaryDirectory()
        home = Path(tmp_ctx.name)
        sec = home / "sec.asc"
        sec.write_text(recipient_sec_armored, encoding="utf-8")
        env0 = {"GNUPGHOME": str(home)}
        r_imp = subprocess.run(
            [gpg, "--batch", "--import", str(sec)],
            env={**__import__("os").environ, **env0},
            capture_output=True,
            timeout=60,
        )
        if r_imp.returncode != 0:
            if tmp_ctx:
                tmp_ctx.cleanup()
            raise GpgCryptoError(
                "IMPORT_SEC_FAILED", r_imp.stderr.decode(errors="replace")[:500]
            )

    work = home / ".agentq_decrypt"
    work.mkdir(exist_ok=True)
    inp = work / "in.asc"
    inp.write_text(armored, encoding="utf-8")
    env = {"GNUPGHOME": str(home)}
    if sender_pubkey_armored:
        pub = work / "sender.pub.asc"
        pub.write_text(sender_pubkey_armored, encoding="utf-8")
        subprocess.run(
            [gpg, "--batch", "--import", str(pub)],
            env={**__import__("os").environ, **env},
            capture_output=True,
            timeout=60,
        )
    cmd = [gpg, "--batch", "--decrypt", str(inp)]
    if recipient_passphrase:
        cmd[1:1] = ["--pinentry-mode", "loopback", "--passphrase-fd", "0"]
    r = subprocess.run(
        cmd,
        env={**__import__("os").environ, **env},
        input=(recipient_passphrase + "\n").encode() if recipient_passphrase else None,
        capture_output=True,
        timeout=120,
    )
    out_bytes = r.stdout
    err = r.stderr.decode("utf-8", errors="replace")
    if tmp_ctx:
        tmp_ctx.cleanup()
    # gpg returns 2 when decryption ok but signature unchecked (no sender pub yet)
    if r.returncode != 0 and not out_bytes:
        raise GpgCryptoError("DECRYPT_FAILED", err[:800])
    if r.returncode != 0 and sender_pubkey_armored:
        raise GpgCryptoError("DECRYPT_FAILED", err[:800])
    if sender_pubkey_armored and "Good signature" not in err:
        raise GpgCryptoError("SIGNATURE_VERIFY_FAILED", err[:800])
    fp = ""
    m = _FINGERPRINT_RE.search(err)
    if m:
        fp = m.group(1).replace(" ", "").upper()
    return out_bytes, fp
