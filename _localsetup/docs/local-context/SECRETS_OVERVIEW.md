---
status: DRAFT
version: 0.1
---

### Secrets overview

This repository uses KeePass as the primary store for infrastructure secrets. The goal is to keep all secret values out of tracked files while still giving agents and humans a stable way to reference them.

Key pieces:

- `secrets/keepass-config.yaml` describes which KeePass database files the repo cares about (for example `secrets/infra.kdbx`) without embedding master passwords or keyfiles.
- `secrets/*-secrets-map.yaml` files map logical IDs such as `mail.box03.cruxexperts.admin` to KeePass entry paths like `Servers/box03/Mail/admin@cruxexperts.com`.
- The `.keepass_secrets/` helper and `ls-keepass-secrets` skill resolve those IDs on demand and call `keepassxc-cli` to read or write entries.

### Referencing secrets in docs

When you need to mention credentials in documentation, reference the logical ID instead of pasting the username and password. For example:

- `Secret ID: mail.box03.cruxexperts.admin`
- `Secret ID: postgres.box03.app1`

When you or an agent need the actual values, run a workflow that calls the `ls-keepass-secrets` skill with that ID. The credentials are shown interactively and never written back into markdown.

### Where the actual secrets live

- Secret values (passwords, tokens, key material) live only in KeePass `.kdbx` databases and in short-lived CLI output.
- KeePass databases, keyfiles, and master passwords must not live under `secrets/` or `.keepass_secrets/`. They stay outside the repo and are managed by humans or external secret managers.

