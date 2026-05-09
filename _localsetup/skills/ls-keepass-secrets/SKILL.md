---
name: ls-keepass-secrets
description: Resolve logical secret IDs through KeePass using repo-local mapping files; optionally bulk-create or rotate secrets without ever writing values into tracked files.
metadata:
  version: "1.0"
compatibility: "Guidance-only unless the adopting repo supplies a helper CLI. Requires Linux or WSL2, Python 3.10+ for any repo helper, keepassxc-cli 2.7+ on PATH, and an interactive TTY for KeePass prompts."
---

# KeePass-backed secrets (ls-keepass-secrets)

## Purpose

Provide a safe pattern for agents and tools to look up and (optionally) create or rotate infrastructure secrets using a KeePass database as the canonical store, while keeping all secret values out of repository files. This skill defines the logical ID model, mapping files, safety rules, and implementation contract for a repo-supplied helper. It does not ship a helper CLI in this repository.

## When to use this skill

- User asks for logins, API keys, or service accounts that already live in KeePass (for example, "give me the login for admin@cruxexperts.com").
- A workflow needs DB credentials or mailboxes for a specific host (for example, `mail.box03.cruxexperts.admin`, `postgres.box03.app1`), and those entries are already mapped into `secrets/*-secrets-map.yaml`.
- You want to bulk-create or rotate accounts (hundreds at a time) with strong random passwords, but you must not paste those passwords into docs or config files.
- You need a stable logical ID for documentation and workflows so you can reference secrets without re-embedding their values.

## Inputs and logical model

### Logical IDs and service types

- Logical IDs follow `service.host.scope.name` form, for example:
  - `mail.box03.cruxexperts.admin`
  - `mail.box03.cruxexperts.info`
  - `minio.box03.root`
  - `postgres.box03.app1`
  - `api.box03.stripe.live`
- Canonical `service_type` values:
  - `mail.mailbox`
  - `db.user`
  - `api.key`
  - `service.account`
  - `ssh.key`
- Normalized secret fields:
  - `id`, `service_type`
  - `username`, `password`, `token`, `url`, `notes`
  - `meta`: dict with service-specific details (for example `domain`, `database`, `env`, `role`, `host`, `port`).

### Repo-local configuration and mapping

- `secrets/keepass-config.yaml`:
  - Holds non-secret metadata about KeePass databases.
  - Example:

    ```yaml
    default_database: "secrets/infra.kdbx"
    databases:
      infra:
        path: "secrets/infra.kdbx"
        keyfile: null          # must point outside the repo when used
        password_source: "prompt"
    bootstrap:
      created_at: null
      created_by: null
    ```

- `secrets/<host>-secrets-map.yaml` (for example `secrets/box03-secrets-map.yaml`):
  - Maps logical IDs to KeePass entry paths and optional metadata, with no secret values:

    ```yaml
    database: "infra"
    entries:
      mail:
        box03:
          cruxexperts:
            admin:
              service_type: "mail.mailbox"
              path: "Servers/box03/Mail/admin@cruxexperts.com"
              username: "admin@cruxexperts.com"
            info:
              service_type: "mail.mailbox"
              path: "Servers/box03/Mail/info@cruxexperts.com"
              username: "info@cruxexperts.com"
      minio:
        box03:
          root:
            service_type: "service.account"
            path: "Servers/box03/MinIO/root"
    aliases:
      mail-address:
        "admin@cruxexperts.com": "mail.box03.cruxexperts.admin"
        "info@cruxexperts.com": "mail.box03.cruxexperts.info"
    ```

- Mapping files are treated as read-only by helpers: agents and CLIs never rewrite them; humans edit them via normal code review.

## Implementation status and prerequisites

- This repository ships this skill as guidance and a contract only. It does not include tracked helper code for reading or writing KeePass entries.
- An adopting repository must provide its own helper CLI before any command examples in this skill can be used operationally.
- The helper must run on Linux or WSL2, have `keepassxc-cli` version 2.7 or newer on `PATH`, and use an interactive TTY unless the repo explicitly documents a hardened non-interactive unlock flow.
- Native Windows is outside this skill's support boundary; use WSL2. Other Unix-like hosts are unvalidated unless the adopting repo tests and documents them.
- If the helper is absent, agents should stop after mapping validation and ask the user to install or link the repo's approved KeePass helper.

## Interfaces described by this skill

This skill does not expose a Python API or bundled command directly. The sections below describe semantic operations that a repo-supplied helper may implement. Use the actual command documented by the adopting repository; do not assume a module name, package path, or function exists unless it is tracked in that repository.

### get_secret(id, fields=None, host=None)

- **Inputs:**
  - `id`:
    - Logical secret ID (`service.host.scope.name`) or an alias such as an email address.
  - `fields`:
    - Optional list (or comma-separated string) of fields to return.
    - Supported field names: `username`, `password`, `url`, `notes`, `meta`, `service_type`.
  - `host`:
    - Optional host name (for example `box03`).
    - If omitted, host is resolved in this order:
      1. CLI `--host` argument, if provided by the caller.
      2. `LOCALSETUP_HOST` environment variable, if set.
      3. Single `*-secrets-map.yaml` file under `secrets/` (auto-selected).
      4. Otherwise, fail with an "ambiguous host, please specify --host" error.

- **Behavior:**
  - Resolve repo root by walking up from `cwd` until `_localsetup/` is found.
  - Load `secrets/keepass-config.yaml` (or apply a safe default if absent).
  - Load the appropriate host map from `secrets/<host>-secrets-map.yaml`.
  - Resolve aliases (for example, mail address to logical ID).
  - Map the logical ID into:
    - KeePass database path (from `keepass-config.yaml`).
    - KeePass entry path (from the host mapping file).
    - Optional `service_type` and `expected_username`.
  - Invoke the adopting repo's approved helper for the `get` operation.
  - The helper:
    - Checks that `keepassxc-cli` is installed and at least at the required version; if not, fails fast with a clear message and installation/upgrade hint.
    - Uses `keepassxc-cli show --format json` or an equivalent KeePassXC-supported read mode to retrieve the entry.
    - Maps KeePass fields (`UserName`, `Password`, `URL`, `Notes`, and others) into a normalized record.
    - Optionally merges mapping metadata (for example, `service_type`, expected `username`).
    - Returns a JSON object on stdout with the requested fields only.

- **Outputs:**
  - JSON object with:
    - `id`: resolved logical ID.
    - Optional `service_type`, `username`, `password`, `token`, `url`, `notes`, `meta`.
  - When `--human` is passed, the CLI prints a short human-readable summary instead of JSON, but still does not write secrets to any file.

### ensure_secrets(batch_spec_path, host=None, force=False, dry_run=False)

- **Inputs:**
  - `batch_spec_path`:
    - Path to a YAML batch spec describing many logical IDs and desired parameters.
    - Example:

      ```yaml
      host: box03
      items:
        - id: mail.box03.cruxexperts.admin
          service: mail.mailbox
          username: "admin@cruxexperts.com"
          generate_password: true
          rotate_password: false
        - id: mail.box03.cruxexperts.info
          service: mail.mailbox
          username: "info@cruxexperts.com"
          generate_password: true
      ```

  - `host`:
    - Optional override for `spec.host`, resolved via the same precedence rules as `get_secret`.
  - `force`:
    - If `false`, mismatches between existing KeePass usernames and mapping spec cause a failure with a clear error.
    - If `true`, allows updating usernames and similar fields in KeePass to match the mapping/batch spec.
  - `dry_run`:
    - When `true`, validates mappings, existence, and diffs but does not write any changes to KeePass.

- **Behavior:**
  - Parse the batch spec (must contain a non-empty list of `items`).
  - For each item:
    - Resolve the logical ID into KeePass DB path and entry path using the host map and `keepass-config.yaml`.
    - Determine `username`:
      - Prefer `item.username`, else mapping `username`, else fail.
    - Probe for existing entries using `keepassxc-cli show`:
      - If entry exists and has a password:
        - When `rotate_password` is `false` and `generate_password` is `false`, treat as reused and do not change it.
        - When `rotate_password` is `true` or `generate_password` is true and no password is present, generate a new password and write it.
      - If entry does not exist:
        - Generate a password when `generate_password` is true; otherwise fail clearly.
    - On username mismatch (existing KeePass vs mapping) and `force` not set, fail with a descriptive error instead of changing the entry.
    - When not in `dry_run`, use the adopting repo's approved helper write path to create or update the entry.
  - Invoke the adopting repo's approved helper for the `ensure` operation.

- **Outputs:**
  - JSON summary on stdout with:
    - `created`: list of `{id, path}` for entries newly created.
    - `reused`: list of `{id, path}` for entries that already existed and were left unchanged.
    - `rotated`: list of `{id, path}` for entries whose passwords were rotated.
    - `errors`: list of `{id, path?, error}` descriptions; callers should fail the overall operation when this is non-empty.
  - No passwords or tokens are written to mapping files, only to KeePass and to the ephemeral JSON output of the run.

## Security and safety rules

- Secrets:
  - Secret values (passwords, tokens, key material) live only in:
    - KeePass `.kdbx` databases.
    - Ephemeral CLI stdout and in-memory structures for the current call.
  - Never write secret values into:
    - Tracked repository files (YAML, markdown, code).
    - Logs, telemetry, or long-lived artifacts.
- KeePass databases and keys:
  - KeePass DB files such as `secrets/infra.kdbx` may be versioned in some repos, but master passwords and keyfiles must be kept outside the repo.
  - `keepass-config.yaml` may reference keyfiles and password sources, but must never contain cleartext secrets.
- Error handling:
  - Error messages must not contain KeePass `show` output or any secret field values.
  - Errors may refer to logical IDs, hosts, KeePass entry paths, and high-level failure reasons only.
- Mapping files:
  - `keepass-config.yaml` and `*-secrets-map.yaml` are safe to track in git because they contain no secrets.
  - CLIs and agents treat these files as read-only; only humans edit them.
- Input hardening:
  - Logical IDs, host names, and paths are validated against safe patterns before being passed to any subprocess.
  - Invalid IDs or suspicious characters cause immediate failures rather than being passed to `keepassxc-cli`.

## Bootstrap and installation behavior

### KeePass CLI availability and installation hints

- On every read/write operation, the repo-supplied helper checks `keepassxc-cli`:
  - If the binary is missing:
    - Fail fast with a clear message: `keepassxc-cli is not installed or not on PATH. Install KeePassXC (including the CLI) from your package manager and ensure keepassxc-cli is available.`
    - Optionally add repo-local docs with distro-specific commands and point to them from this error.
  - If the version is older than the configured minimum (for example `2.7.0`):
    - Fail fast with a message like `keepassxc-cli version X.Y.Z is too old. Install at least 2.7.0.`
  - The skill does not try to run package managers by itself; it only proposes installation or upgrade steps for a human to run.

### Config and database bootstrap

- Missing helper implementation:
  - If the adopting repo does not track or install a helper CLI, agents stop and report that this skill is guidance-only in the current environment.
  - Do not invent a command name or module path. Link to the repo's tracked helper when one exists.
- Missing `secrets/keepass-config.yaml`:
  - Helpers and this skill:
    - Print a short error explaining that `secrets/keepass-config.yaml` is required.
    - Show a minimal template the user can copy into `secrets/keepass-config.yaml`.
    - Exit non-zero; they never create the file automatically.
- Missing or invalid DB path:
  - If the configured DB path does not exist:
    - Explain that a KeePass DB is required and that the user must either:
      - Point `keepass-config.yaml` at an existing `.kdbx`, or
      - Create a new DB manually via KeePassXC UI or `keepassxc-cli db-create`.
    - Do not auto-create the DB or generate master passwords.
  - KDF settings:
    - When humans create a new DB they should configure Argon2id with:
      - Memory cost on the order of 128-256 MiB.
      - Time cost tuned for around 2-3 seconds on the current host.
      - Parallelism of 2-4.
    - This tuning is done once at DB creation time, not on each secret operation.
- Missing host mapping file:
  - When the requested host map `secrets/<host>-secrets-map.yaml` is missing:
    - Helpers and this skill emit a clear error naming the missing file.
    - They refuse to proceed until the mapping file exists and passes basic validation.

## Interaction constraints and platform support

- Interactivity:
  - For v1, helper implementations should expect an interactive TTY:
    - They rely on `keepassxc-cli` to prompt for master passwords when required.
    - If stdin is not a TTY (for example in CI), they fail fast with a clear message instead of hanging.
  - Non-interactive modes (for example env-var based master passwords) are a future, opt-in extension and must be carefully documented.
- Supported platforms:
  - v1 is scoped to Linux and WSL2 hosts where `keepassxc-cli` is installed and on PATH.
  - Native Windows is unsupported for this skill. Run from WSL2 instead.
  - On unsupported platforms, helpers should fail fast with a short explanation.

## Documentation and usage patterns

- Secrets overview:
  - Repositories that adopt this skill should add a short doc (for example `docs/local-context/SECRETS_OVERVIEW.md`) that:
    - States that secrets live in KeePass, not in repo files.
    - Mentions `secrets/keepass-config.yaml` and `secrets/*-secrets-map.yaml` as the mapping layer.
    - Shows how to reference secrets by logical ID in docs instead of pasting values.
    - States whether the repo has an actual helper CLI installed, where it is tracked, and which platforms have been tested.
  - Treat `docs/local-context/SECRETS_OVERVIEW.md` as repo-local adoption/status documentation, not as the canonical implementation source. The canonical implementation source is the tracked helper code in the adopting repository, if present.
- Referencing in docs:
  - In context docs, prefer patterns like:
    - `Secret ID: mail.box03.cruxexperts.admin`
    - `Secret ID: postgres.box03.app1`
  - When a human needs the credentials, they run a workflow that calls this skill with that ID and shows the result interactively.
- Login-card helpers:
  - Higher-level workflows can build convenience helpers (for example "show login for admin@cruxexperts.com") by:
    - Mapping an email address to a logical ID via `aliases` in the host map.
    - Calling the repo's approved `get_secret` workflow or helper.
    - Presenting host, username, and password in the chat only, never committing them to disk.
