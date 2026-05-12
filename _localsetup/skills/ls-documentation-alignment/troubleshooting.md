# Troubleshooting

## `check --ci` fails after generated docs refresh

Run:

```bash
python3 _localsetup/tools/docs_alignment.py --repo-root . audit
```

Review critical and major findings first.

## A count is wrong

Inspect the claim:

```bash
python3 _localsetup/tools/docs_alignment.py --repo-root . explain --claim-id skill_count
```

Fix the source manifest or regenerate docs. Do not hand-edit generated files.

## A link is reported missing

Prefer a relative Markdown link from the source file to the target. If the target is intentionally external, use an explicit URL.

## A generated file is not included in version sync

Add it to `_localsetup/v3/versioning.py` generated-path candidates and add a focused test.
