# Documentation Alignment Runbook

1. Create or resume a run ledger.
2. Run `inventory` and `audit`.
3. If broad, delegate scouts for code truth, docs surfaces, generated ownership, external standards, assets/CI, and package conventions.
4. Run `plan`.
5. Apply generated fixes.
6. Apply supported public fixes only when backed by the truth map.
7. Refresh all generated docs.
8. Run `check --ci`.
9. Run repo validation gates.
10. Inspect the diff and ask for a final read-only review.

For Localsetup, the minimum validation is:

```bash
python3 _localsetup/tools/generate_docs_artifacts.py --repo-root .
python3 _localsetup/tools/localsetup_v3.py --repo . generate-docs
python3 _localsetup/tools/localsetup_v3.py --repo . validate-catalog
python3 _localsetup/tools/docs_alignment.py --repo-root . check --ci
git diff --check
```
