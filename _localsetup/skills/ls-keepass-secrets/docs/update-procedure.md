# Update Procedure

1. Update scripts, schemas, examples, and docs together.
2. Run focused tests for `ls-keepass-secrets`.
3. Refresh generated docs:

```bash
python3 _localsetup/tools/generate_docs_artifacts.py --repo-root .
python3 _localsetup/tools/localsetup_v3.py --repo . generate-docs
```

4. Run catalog and framework validation.
5. Inspect `git diff --check` before publishing.
