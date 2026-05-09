# Agent Q transport client – user guide

**Purpose:** Version stamp, key generation, registry validation, file_drop ingest (decrypt armored blob into queue `in/`).

## Prerequisites

- Python 3.10+, framework deps (PyYAML, python-frontmatter, cryptography, PGPy)
- **gpg** on PATH for `key-gen` (batch key in temp homedir, no host keyring pollution)

## Commands

```bash
# From repo root
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py version
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py key-gen /path/to/outdir
# Writes agentq.pub.asc + agentq.sec.asc; print fingerprint for registry

python3 _localsetup/tools/agentq_transport_client/agentq_cli.py registry-validate _localsetup/config/agent_trust_registry.example.yaml --skip-keys

# Decrypt a sealed file into queue (recipient must own private key)
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py ingest-blob /path/to/x.agentq.asc \
  --queue .agent/queue --privkey /path/to/agentq.sec.asc \
  --registry path/to/agent_trust_registry.yaml

# Ship file_drop: seal to recipient pubkey, write .agentq.asc then .agentq.ready
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py ship-file-drop \
  --manifest path/to/spec.prd.md --pubkey recipient.pub.asc --out /sync/outgoing --stem run1 \
  --queue .agent/queue
# Manifest may include pre_ship_checks as argv lists or objects, for example:
# {"pre_ship_checks": [["python3", "-m", "pytest", "-q"]]}
# Allowed commands are pytest, python3 --version, and python3 -m pytest; shell operators are rejected.

# Strict sign-then-encrypt (gpg): signer GNUPGHOME has secret; gpg imports recipient pub for encryption
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py ship-file-drop \
  --manifest manifest.json --pubkey recipient.pub.asc --out /sync/out --stem run1 \
  --signer-gnupghome ~/.gnupg-agentq --signer-uid your@email
# Recipient ingest with --strict-gpg + --registry: Good signature must match from_agent_id in registry.
# Strict failures reject or quarantine with a ledger code; they never fall back to encrypt-only ingest.
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py ingest-blob /sync/out/run1.agentq.asc \
  --queue .agent/queue --privkey recipient.sec.asc --registry agent_trust_registry.yaml --strict-gpg

# Optional ready marker: first line of .ready can be `sha256 <64hex>` to match sealed file (truncated sync guard)
# Ship directory as single tar.gz attachment (default max 20MB)
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py ship-bundle /path/to/dir \
  --pubkey recipient.pub.asc --out /sync/out --stem mybundle --queue .agent/queue

# Retry IMAP move after promote if policy blocked first time (ledger pending_processed_move)
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py mail-move-retry --queue .agent/queue --account your_account_id

# Prune archive/ by age or max total GB
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py archive-prune .agent/queue/archive --days 90 --max-gb 10 --dry-run

# Move in/* with ack_required to pending/ (or --list to show in/)
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py queue-pending --queue .agent/queue --list
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py queue-pending --queue .agent/queue

python3 _localsetup/tools/agentq_transport_client/agentq_cli.py prune-processed /path/to/processed --days 30
# Add --dry-run to list only.

# Poll registry inbound roots for a peer agent_id (or --root dir, repeatable)
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py file-drop-poll \
  --queue .agent/queue --privkey agentq.sec.asc --registry agent_trust_registry.yaml --agent agent-b

# Mail pull (IMAP): UNSEEN -> decrypt -> promote -> move to Processed folder
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py mail-pull \
  --queue .agent/queue --account your_account_id --post-mailbox LocalsetupAgentQ/Processed

# Mail ship: requires recipient OpenPGP pubkey in account crypto env
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py ship-mail \
  --account your_account_id --from-addr you@x --to peer@x --manifest path/to/spec.prd.md

python3 _localsetup/tools/agentq_transport_client/agentq_cli.py stamp-prd path/to/spec.prd.md
python3 _localsetup/tools/agentq_transport_client/agentq_cli.py key-fingerprint agentq.pub.asc
```

## file_drop writer order

1. Write payload to `name.agentq.asc` (armored OpenPGP from `seal_inner_json` / counterpart).
2. Write sibling `name.agentq.ready` last (empty or first line `sha256 <hex>` optional).

**Sidecar:** `ship-file-drop` also writes `stem.agentq.sidecar.json` (audit). **Attachments:** `attachments[]` with `content_b64` + `sha256` extracted under `in/<id>/attachments/`; mismatch -> `ingest_checksum_fail` in ledger.

## Inner manifest (minimum)

- `manifest_version` (string)
- `from_agent_id` (string; must match registry signer when signature binding is enforced)
- `prd_body` (optional): written as `prd_filename` default `ingested.prd.md` into `in/<blob_id>/`

## Related

- [_localsetup/docs/AGENTIC_AGENT_Q_SCENARIOS.md](../../../docs/AGENTIC_AGENT_Q_SCENARIOS.md) (same machine different repos, remote, mail vs file_drop)
- [_localsetup/docs/AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](../../../docs/AGENTIC_AGENT_TO_AGENT_PROTOCOL.md)
- [_localsetup/docs/AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md](../../../docs/AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md)
