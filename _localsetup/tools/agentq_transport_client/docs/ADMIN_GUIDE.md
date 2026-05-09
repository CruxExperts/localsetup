# Agent Q transport client – admin guide

## Policy

- **Adapter ingest:** Only OpenPGP armored blobs are promoted automatically; plaintext adapter ingest is out of spec.
- **Registry:** `agent_trust_registry` maps fingerprint to `agent_id`; inner manifest `from_agent_id` must match signer when strict path is used.
- **Mail post-ingest:** Move processed messages to `LocalsetupAgentQ/Processed` (or config) to avoid UNSEEN replay without ledger.
- **file_drop:** Writer order: payload complete then ready marker last. Sealed extension default `.agentq.asc`.

## Transport choice

- **file_drop:** Best for shared sync folders (Drive/Dropbox sync client, NFS). Same crypto as mail; no IMAP.
- **Mail:** `ship-mail` uses encrypt-only outer; **`ship-mail-strict`** sends gpg sign-then-encrypt blob via `preencrypted_openpgp_armored` (mail skill bypass). Recipient **pull** must decrypt with PGPy-compatible key (or gpg-generated key usable by PGPy decrypt).
- **drive_sync / dropbox_sync:** Use `FileDropAdapter` / `StubDriveAdapter` with sync folder roots only; no cloud API in v1.

## Strict gpg failure handling

- `ingest-blob --strict-gpg` requires `--registry`; otherwise ingest rejects with `STRICT_GPG_REGISTRY_REQUIRED`.
- Decrypt, signature, signer binding, and registry lookup failures are ledgered as `ingest_verify_fail` and copied to `inbox/.quarantine/<transport_id>/error.txt`.
- Strict mode does not fall back to the encrypt-only PGPy path. Re-run after fixing key material or registry bindings.

## Registry edit

- Edit `agent_trust_registry.yaml`; run `registry-validate` with keys on disk before production.
- **Rotation:** Add `public_keys` list per agent; validator loads all and maps fingerprints; remove old after cutover.

## Key pre-share and rotation

1. `key-gen` or gpg batch in dedicated GNUPGHOME.
2. `key-export` / `key-fingerprint` to share pubkey; never commit `.sec.asc`.
3. Recipient imports via `key-import` into their GNUPGHOME.
4. On rotation, add new pubkey path to registry, ship with both keys until peers updated, then drop old path.

## Conflict filenames

- **ignore_globs** in queue config: `*conflicted copy*`, `*.tmp`, `~*`. Writers must not ingest until sync settles.
- Ready marker optional **sha256** first line catches truncated uploads.

## Insecure drop rationale

- OpenPGP sign-then-encrypt means **path can be public**; confidentiality + integrity come from crypto, not from hiding the folder.

## Force ingest audit

- `ingest-blob --force --operator <id> --reason "<text>"` appends `ingest_forced` to ledger. Quarantine copy retained until operator deletes.

## Mail automation profile

- Policy must allow `smtp.send_encrypted` and `imap.move_messages` for the automation account.
- If move is `CONFIRMATION_REQUIRED`, run `mail-move-retry --confirm-token <token>` after approving.
- **Strict mail ship:** `ship-mail-strict` requires signer GNUPGHOME + recipient pubkey file; no double encryption.

## Multi-recipient (phase 2)

- Manifest `to_agent_ids`: list of agent ids. CLI `ship-file-drop-multi --manifest m.json --registry r.yaml --out /drop` seals one blob per id using each agent's `public_key_path` from registry.

## File lock before verify

- `file-drop-poll --use-lockfile`: fcntl exclusive lock on `<sealed>.lock` before move to processing (NFS-style shared roots).

## Version mismatch

- PRDs may carry `localsetup_framework_version`. Compare to repo VERSION; policy `warn` | `block` | `allow_log` in queue config.

## Rollback

- Ledger and quarantine dirs record forced ingests. Do not delete ledger without understanding idempotency.

## Related

- [_localsetup/config/agent_queue.example.yaml](../../../config/agent_queue.example.yaml)
- [_localsetup/config/agent_trust_registry.example.yaml](../../../config/agent_trust_registry.example.yaml)
- [_localsetup/skills/ls-mail-protocol-control/SKILL.md](../../../skills/ls-mail-protocol-control/SKILL.md)
- [DEFERRED.md](DEFERRED.md) – short deferred list; Part 19 in build spec for ordered backlog
