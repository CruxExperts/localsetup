# Architecture

`localsetup_secrets.py` is a JSON-first command wrapper for logical secret IDs. It resolves config, loads a secret map, resolves aliases, then dispatches to a backend.

Backends:

- `keepassxc`: primary operational backend. It detects `keepassxc-cli` locally and uses `subprocess.run([...], shell=False)`. The initial implementation does not open real vaults during tests and does not automate master password handling.
- `fake`: deterministic file-backed test backend for CI and examples. It must not be used as a real secret store.

Every command returns an envelope with `ok`, `command`, `data`, `warnings`, `errors`, `sources`, `sensitive`, and `redactions`.
