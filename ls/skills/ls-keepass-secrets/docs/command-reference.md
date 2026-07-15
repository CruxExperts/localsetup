# Command Reference

Run from the skill directory or pass paths explicitly:

```bash
python3 scripts/localsetup_secrets.py doctor
```

Commands:

- `doctor`: show runtime, config, map path, and backend availability.
- `config-show`: show resolved non-secret config.
- `config-init`: write `.localsetup/secrets/config.yaml` with `--apply`.
- `config-validate`: validate backend and config shape.
- `map-validate`: validate and flatten map entries and aliases.
- `list`: list mapped IDs and fake backend entries.
- `search`: search mapped IDs and backend entries.
- `reference`: parse a supported secret reference.
- `resolve`: resolve one ID or reference. Protected fields are redacted unless `--show-sensitive` is passed.
- `ensure`: create/reuse/rotate entries through the backend; dry-run unless `--apply`.
- `set`: set a safe field from an argument or stdin; dry-run unless `--apply`.
- `rotate`: rotate one entry; dry-run unless `--apply`.
- `delete`: delete one entry; dry-run unless `--apply`.
- `audit`: report map consistency findings.
- `export-env`: produce redacted env bindings by default.
- `render-template`: replace `{{secret:<id>:<field>}}` references.
- `vault-info`: show backend metadata.
- `vault-init`: reserved dry-run vault initialization flow.
- `vault-backup`: copy a configured database with `--apply`.
- `schema-dump`: print a built-in command contract.
