#!/usr/bin/env python3
# Purpose: Generate OpenPGP keypair via gpg batch in temp homedir; export armored.
# Created: 2026-03-09
# Last updated: 2026-03-09

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

BATCH_SPEC = """
%no-protection
Key-Type: RSA
Key-Length: 2048
Name-Real: AgentQ
Name-Email: agentq@localsetup
Expire-Date: 0
%commit
"""


def generate_keypair_gnupg(output_dir: Path) -> tuple[Path, Path, str]:
    """Ephemeral homedir, batch gen, export pub+sec armored. Returns paths and fingerprint."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as gnupg_home:
        home = gnupg_home
        subprocess.run(
            ["gpg", "--homedir", home, "--batch", "--gen-key"],
            input=BATCH_SPEC.encode(),
            capture_output=True,
            timeout=120,
            check=True,
        )
        r2 = subprocess.run(
            [
                "gpg",
                "--homedir",
                home,
                "--batch",
                "--with-colons",
                "--fingerprint",
                "--list-secret-keys",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        fp = ""
        for line in r2.stdout.splitlines():
            if line.startswith("fpr:"):
                fp = line.split(":")[9]
                break
        if not fp:
            raise RuntimeError("No fingerprint from gpg.")
        pub_path = output_dir / "agentq.pub.asc"
        priv_path = output_dir / "agentq.sec.asc"
        with open(pub_path, "wb") as f:
            subprocess.run(
                ["gpg", "--homedir", home, "--batch", "--armor", "--export", fp],
                stdout=f,
                timeout=30,
                check=True,
            )
        with open(priv_path, "wb") as f:
            subprocess.run(
                ["gpg", "--homedir", home, "--batch", "--armor", "--export-secret-key", fp],
                stdout=f,
                timeout=30,
                check=True,
            )
        return pub_path, priv_path, fp


def generate_keypair(output_dir: Path, passphrase: str = "", key_size: int = 2048) -> tuple[Path, Path]:
    """Generate keypair; passphrase/key_size reserved for future gpg pin."""
    pub, priv, _ = generate_keypair_gnupg(output_dir)
    return pub, priv
