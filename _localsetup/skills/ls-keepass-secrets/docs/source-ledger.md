# Source Ledger

Access date: 2026-05-12.

| source | observed fact | impact | confidence | conflicts |
|---|---|---|---|---|
| Local repo `_localsetup/skills/ls-keepass-secrets/SKILL.md` | The previous skill was guidance-only and shipped no helper CLI. | This implementation refactors the existing skill instead of adding a duplicate. | High | None |
| Local repo `_localsetup/docs/INPUT_HARDENING_STANDARD.md` | External input must be sanitized, validated, and handled with actionable errors. | CLI validates IDs, aliases, env names, YAML roots, and subprocess calls use `shell=False`. | High | None |
| Local repo `pyproject.toml` / `uv.lock` | PyYAML is already a framework dependency. | YAML config/map parsing uses PyYAML without adding a new dependency. | High | None |
| Local repo `git status` / `git rev-parse` | Repo is `CruxExperts/localsetup`, branch `main`, commit `ce904765b04d8fc424ec0006fe76cead2f7806c8` was the plan baseline. | Generated docs and tests are run against the active worktree, not memory. | Medium | Commit may advance during local work. |
| Local Python | Python `3.12.3` available in this environment. | CLI targets Python 3.12+ and is tested on the available local runtime. | High | None |
| Local `keepassxc-cli --version` | Plan observed local KeePassXC CLI `2.7.12`. | KeePassXC backend is primary, but tests avoid real vault access. | Medium | CLI may not be installed in every environment. |
| KeePassXC downloads | KeePassXC publishes platform downloads and CLI distribution guidance. | Installation docs point users to official packages instead of bundling installers. | Medium | External packaging can change. |
| KeePassXC GitHub releases / 2.7.12 notes | `2.7.12` is the plan-observed current local release. | Doctor/verification reports local version but does not upgrade. | Medium | Latest release can change after access date. |
| KeePassXC docs / Getting Started | KeePassXC uses KDBX databases and interactive unlock flows. | The first implementation does not automate master password handling. | High | None |
| KeePassXC signature verification docs | Official downloads can be signature-verified. | Security docs recommend verifying downloaded installers. | High | None |
| Arch `keepassxc-cli` man page | CLI supports command-oriented operations including show/add/edit patterns. | Backend wrapper uses argv arrays and conservative standard fields. | Medium | Distribution man pages can vary by version. |
| KeePass KDBX 4 reference | KDBX is the KeePass database container format. | Threat model treats `.kdbx` as sensitive even when encrypted. | High | None |
| OWASP Key Management Cheat Sheet | Key material needs separation, rotation, and least exposure. | Config/map files reject embedded secret-like values. | High | None |
| NIST SP 800-57 Part 1 Rev. 5 | Key management requires lifecycle controls and protection of secret material. | Rotation and backup commands are explicit and dry-run by default. | High | None |
| PyKeePass docs | PyKeePass can manipulate KeePass files from Python. | PyKeePass is documented as a future optional backend, not added as a dependency. | High | None |
