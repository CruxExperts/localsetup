# Agent Q transport client – troubleshooting

## stamp-prd fails with ImportError

Install frontmatter: `python3 -m pip install python-frontmatter` (or full framework install with deps).

## key-fingerprint fails

Install PGPy: `python3 -m pip install PGPy`. Key file must be armored OpenPGP.

## version shows 0.0.0

VERSION file missing at repo root. Ensure you run from project root or set paths per path_resolution.

## Decrypt or verify fails on ingest

- Confirm sender public key is in registry and path is readable.
- In strict mode, missing registry returns `STRICT_GPG_REGISTRY_REQUIRED`; signature or decrypt failures quarantine the blob under `inbox/.quarantine/<transport_id>/`.
- Use force ingest with reason only after fixing keys and confirming the sender out of band (see build spec Part 8).

## Duplicate processing

Ledger should record transport id (IMAP UID or blob hash). If ledger missing, re-ingest risk exists; implement ledger before production use.

## Iteration attach-back too large

Use manual handoff or link-based delivery per protocol; mail size limits apply.
