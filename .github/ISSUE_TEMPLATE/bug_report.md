---
name: Bug report
about: Report an install, docs, skill, workflow, or packaging problem
title: "bug: "
labels: bug
assignees: ''

---

## Summary

Describe the problem in one or two sentences.

## Localsetup version

- Version from `cat VERSION`:
- Commit or release tag:

## Environment

- OS and version:
- WSL2 context, if on Windows:
- Shell:
- Python version:
- Git version:

## Localsetup target

- Platform ID: `cursor`, `claude-code`, `codex`, `openclaw`, `kilo`, `opencode`, or `all`
- Pack or workflow ID, if relevant:
- Skill ID, if relevant:
- Install mode: `symlink`, `portable`, managed venv, or other
- Repo path shape: local clone, WSL path, remote/VM, or container

## Command run

```bash

```

## Expected behavior

What should have happened?

## Actual behavior

What happened instead?

## Validation output

Paste the shortest relevant output from commands such as:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . validate-catalog
./_localsetup/tools/verify_context
./_localsetup/tools/verify_rules
python3 -m pytest _localsetup/tests -q
```

## Generated docs or package boundary

- Does this involve generated docs? yes/no
- Does this involve package contents, private paths, or leaks? yes/no
- If yes, name the generated file or package artifact:

## Additional context

Add screenshots, short logs, or links to related issues only if they help reproduce the problem.
