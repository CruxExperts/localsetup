# Agent Usage Patterns

Use logical IDs in docs and workflows, never secret values.

For discovery:

```bash
python3 scripts/localsetup_secrets.py map-validate --map examples/map.yaml
python3 scripts/localsetup_secrets.py reference '{{secret:mail.box03.example.admin:password}}'
```

For tests:

```bash
python3 scripts/localsetup_secrets.py resolve mail.box03.example.admin --backend fake --map examples/map.yaml
```

For real vaults, confirm the user expects an interactive KeePassXC operation before resolving sensitive fields.
