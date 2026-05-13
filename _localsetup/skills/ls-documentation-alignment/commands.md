# Documentation Alignment Command Reference

All commands are run from the repository root.

| Command | Purpose |
|---|---|
| `python3 _localsetup/tools/docs_alignment.py --repo-root . inventory` | Print the scanned docs, assets, CLI, CI, skills, workflows, and platforms. |
| `python3 _localsetup/tools/docs_alignment.py --repo-root . audit` | Print JSON findings without writing files. |
| `python3 _localsetup/tools/docs_alignment.py --repo-root . plan` | Group findings into generated, public-doc, lifecycle, asset, CI, and manual-review buckets. |
| `python3 _localsetup/tools/docs_alignment.py --repo-root . apply --scope generated` | Refresh generated alignment artifacts. |
| `python3 _localsetup/tools/docs_alignment.py --repo-root . apply --scope public` | Apply supported public-doc wording/count fixes. |
| `python3 _localsetup/tools/docs_alignment.py --repo-root . apply --scope assets` | Refresh asset manifest and `assets/README.md`. |
| `python3 _localsetup/tools/docs_alignment.py --repo-root . apply --scope all --dry-run` | Show write targets without mutating files. |
| `python3 _localsetup/tools/docs_alignment.py --repo-root . check --ci` | Read-only CI gate; exits non-zero for critical or major findings. |
| `python3 _localsetup/tools/docs_alignment.py --repo-root . explain --claim-id skill_count` | Show backing source files for a claim. |
| `python3 _localsetup/tools/localsetup_v3.py --source-root . docs-align check --ci` | Run through the Localsetup CLI wrapper. |
