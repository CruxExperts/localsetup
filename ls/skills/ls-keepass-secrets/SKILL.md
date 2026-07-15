---
name: ls-keepass-secrets
description: Use when resolving logical secret IDs through KeePassXC using safe mapping files, JSON-first CLI commands, and redacted output by default.
metadata:
  version: "1.1"
compatibility: "Linux/WSL2 focused; Python 3.12+; PyYAML; keepassxc-cli 2.7+ for the operational KeePassXC backend."
---

# KeePass-backed secrets

Use this skill when a workflow needs a secret value by logical ID without writing that value into a repository, logs, docs, or long-lived artifacts.

## Commands

Primary CLI:

```bash
python3 scripts/localsetup_secrets.py --help
```

Capability check:

```bash
python3 scripts/verify_keepassxc.py --format json
```

The CLI emits JSON envelopes by default:

```json
{
  "ok": true,
  "command": "map-validate",
  "data": {},
  "warnings": [],
  "errors": [],
  "sources": [],
  "sensitive": false,
  "redactions": []
}
```

Use `--format human` only for interactive display. Diagnostics are redacted. Protected values require `--show-sensitive`.

## Logical IDs

Canonical IDs are lowercase and may contain letters, digits, dots, underscores, and hyphens:

```text
mail.box03.example.admin
postgres.box03.app1
api.box03.stripe.live
```

Aliases, including email-like aliases, may be declared in map files. Ambiguous aliases fail clearly.

## References

Supported forms:

```text
Secret ID: mail.box03.example.admin
{{secret:mail.box03.example.admin:password}}
secret://localsetup/repo/default/mail.box03.example.admin#field=password
```

See [docs/reference-format.md](docs/reference-format.md).

## Config and Maps

Resolution order:

1. CLI flags.
2. `LOCALSETUP_SECRETS_*` environment variables.
3. Repo-local `.localsetup/secrets/config.yaml` and map.
4. Legacy `secrets/keepass-config.yaml` plus `secrets/*-secrets-map.yaml`.
5. Global `~/.config/localsetup/secrets/config.yaml` and `~/.local/share/localsetup/secrets/maps/default.yaml`.

Config and map files may contain metadata, entry paths, usernames, URLs, and aliases. They must not contain passwords, tokens, key material, or passphrases.

Examples live in [examples/](examples/). Contract schemas live in [schemas/](schemas/).

## Backends

- `keepassxc`: primary backend. Uses `keepassxc-cli` with `subprocess.run([...], shell=False)`. Safe writes are limited to `UserName`, `Password`, `URL`, `Notes`, title, and path.
- `fake`: test backend for placeholder data and CI.
- PyKeePass: future optional backend only; not installed or required by this skill.

## Safety Rules

- Never put secret values in tracked files.
- Keep `.kdbx`, keyfiles, and `.env` files out of Git.
- Use dry-run output first; write commands require `--apply`.
- Do not request protected values unless the user explicitly needs them for the current operation.
- Do not open, create, or inspect real vaults during tests.

## Documentation

- [Architecture](docs/architecture.md)
- [Command reference](docs/command-reference.md)
- [Config resolution](docs/config-resolution.md)
- [Global vs repo-local scope](docs/global-vs-repo-local-scope.md)
- [Vault backends](docs/vault-backends.md)
- [KeePassXC installation and versioning](docs/keepassxc-installation-versioning.md)
- [Portable vault files](docs/portable-vault-files.md)
- [Migration from v1](docs/migration-from-v1.md)
- [Security threat model](docs/security-threat-model.md)
- [Agent usage patterns](docs/agent-usage-patterns.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Update procedure](docs/update-procedure.md)
- [Source ledger](docs/source-ledger.md)
- [Version ledger](docs/version-ledger.md)
