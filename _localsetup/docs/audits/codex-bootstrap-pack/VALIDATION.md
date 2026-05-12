---
status: ACTIVE
version: 3.6
date: 2026-05-10
---

# Codex Bootstrap-Pack Validation

## Command Results

| Command | Result | Evidence |
|---|---|---|
| `date '+%Y%m%d-%H%M%S %Y-%m-%d %H:%M:%S %Z %z'` | pass | `20260510-223606 2026-05-10 22:36:06 CDT -0500` |
| `git status --short` at start | pass | Initial worktree was clean |
| `codex --version` | pass | `codex-cli 0.130.0` |
| `codex debug --help` | pass | `prompt-input` and `models` debug commands are available |
| `codex debug prompt-input 'bootstrap-pack audit prompt-load probe'` | pass | Rendered model-visible prompt input JSON |
| `python3 _localsetup/tools/generate_docs_artifacts.py --repo-root .` | pass | Regenerated skills, workflow registry, quick ref, facts, and workflow catalog |
| `python3 _localsetup/tools/localsetup_v3.py --repo . generate-docs` | pass | Regenerated aliases, migration map, platform adapters, skill packs, workflow catalog, and implementation file map |
| `python3 _localsetup/tools/localsetup_v3.py --repo . plan --packs bootstrap` | pass | Effective install plan includes 12 skills and 3 workflow packages |
| `./_localsetup/tools/verify_context` | pass | Context verification complete |
| `./_localsetup/tools/verify_rules` | pass | Rule verification complete |
| `python3 _localsetup/tools/localsetup_v3.py --repo . validate-catalog` | pass | `{"ok": true, "issues": []}` |
| `python3 _localsetup/tools/localsetup_v3.py --repo . scan-migration` | pass | Exit 0; reported 599 informational legacy-name references in ignored run ledgers, generated migration/alias surfaces, and lockfile |
| `python3 _localsetup/skills/ls-framework-audit/scripts/run_framework_audit.py` | pass | `Errors: 0, Warnings: 0` |
| `git diff --check` | pass | No whitespace errors |
| `./_localsetup/tests/automated_test.sh` | pass | `9 passed, 0 failed` |
| `python3 -m pytest _localsetup/tests` | pass | `114 passed in 20.31s` |
| Inline schema/artifact parse checker | pass | Exact command recorded below; parsed `pack.yaml`, bootstrap metadata, generated JSON, global Codex config, and agent TOMLs |
| Inline bootstrap membership checker | pass | Exact command recorded below; `included_skills`, `effective_install_skills`, and `included_workflows` match repo selectors |
| Inline changed-markdown local link checker | pass | Exact command recorded below; new and changed local markdown links resolved |
| Final read-only reviewer | pass | Original audit reviewer found no blocking audit findings; publish-pass reviewer finding on effective install skills was resolved and validation rerun |

## Reproducible Checker Commands

```bash
python3 - <<'PY'
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

root = Path(".").resolve()
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from _localsetup.v3.skills import selected_skill_names
from _localsetup.v3.workflows import selected_workflow_names

required = [
    "_localsetup/docs/audits/codex-bootstrap-pack/AUDIT_REPORT.md",
    "_localsetup/docs/audits/codex-bootstrap-pack/FINDINGS.yaml",
    "_localsetup/docs/audits/codex-bootstrap-pack/REMEDIATION_PLAN.md",
    "_localsetup/docs/audits/codex-bootstrap-pack/REMEDIATION_TASKS.yaml",
    "_localsetup/docs/audits/codex-bootstrap-pack/VALIDATION.md",
]
required += sorted(str(p.relative_to(root)) for p in (root / "_localsetup/docs/audits/codex-bootstrap-pack/agent-reports").glob("*.md"))

missing = [p for p in required if not (root / p).is_file()]
if missing:
    raise SystemExit(f"missing required artifacts: {missing}")

for rel in [
    "_localsetup/config/pack.yaml",
    "_localsetup/docs/bootstrap-packs/codex-agent-team/metadata.yaml",
    "_localsetup/docs/audits/codex-bootstrap-pack/FINDINGS.yaml",
    "_localsetup/docs/audits/codex-bootstrap-pack/REMEDIATION_TASKS.yaml",
]:
    yaml.safe_load((root / rel).read_text(encoding="utf-8"))

for rel in [
    "_localsetup/docs/_generated/workflow-catalog.json",
    "_localsetup/docs/_generated/facts.json",
    "_localsetup/docs/_generated/skill_aliases.json",
]:
    json.loads((root / rel).read_text(encoding="utf-8"))

for rel in [
    os.path.expanduser("~/.codex/config.toml"),
    *[str(p) for p in Path(os.path.expanduser("~/.codex/agents")).glob("*.toml")],
]:
    tomllib.loads(Path(rel).read_text(encoding="utf-8"))

pack = yaml.safe_load((root / "_localsetup/config/pack.yaml").read_text(encoding="utf-8"))
metadata = yaml.safe_load((root / "_localsetup/docs/bootstrap-packs/codex-agent-team/metadata.yaml").read_text(encoding="utf-8"))
if sorted(metadata["included_skills"]) != sorted(pack["packs"]["bootstrap"]):
    raise SystemExit("metadata included_skills does not match direct bootstrap pack membership")
if sorted(metadata["included_workflows"]) != sorted(pack["workflow_packs"]["bootstrap"]):
    raise SystemExit("metadata included_workflows does not match bootstrap workflow pack membership")
if sorted(metadata["effective_install_skills"]) != selected_skill_names(root, ["bootstrap"]):
    raise SystemExit("metadata effective_install_skills does not match selected_skill_names(repo, ['bootstrap'])")
if sorted(metadata["included_workflows"]) != selected_workflow_names(root, ["bootstrap"]):
    raise SystemExit("metadata included_workflows does not match selected_workflow_names(repo, ['bootstrap'])")

status = subprocess.check_output(["git", "status", "--short", "--untracked-files=all"], text=True)
changed_md = []
for line in status.splitlines():
    path = line[3:]
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    if path.endswith(".md") and (root / path).is_file():
        changed_md.append(path)

pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
bad = []
for rel in changed_md:
    text = (root / rel).read_text(encoding="utf-8")
    base = (root / rel).parent
    for target in pattern.findall(text):
        target = target.strip()
        if (
            not target
            or target.startswith(("#", "http://", "https://", "mailto:", "file:"))
            or target.startswith("<")
        ):
            continue
        target_path = target.split("#", 1)[0]
        if not target_path:
            continue
        resolved = (base / target_path).resolve()
        if not resolved.exists():
            bad.append(f"{rel}: {target}")

if bad:
    raise SystemExit("broken local markdown links:\n" + "\n".join(bad))

print("REQUIRED_OK")
print("PARSE_OK")
print("BOOTSTRAP_MEMBERSHIP_OK")
print("LINK_OK")
PY
```

## Prompt-To-Artifact Checklist

| Requirement | Evidence | Status |
|---|---|---|
| Generate an explicit plan | Ledger `.codex/runs/20260510-223606-codex-bootstrap-pack-audit.md` and controller update | met |
| Use reviewer/auditor/explorer/research/legacy-inventory subagents | Five saved reports under `agent-reports/`, including final reviewer | met |
| Save all audit artifacts | Required top-level artifacts plus subagent reports exist under `_localsetup/docs/audits/codex-bootstrap-pack/` | met |
| Implement only low-risk docs/prompt/index/metadata fixes | Changes are repo-local docs, generated docs, pack metadata, and Codex template pointer | met |
| Do not make destructive changes | No delete/rename/reset/chmod operations were used | met |
| Do not change external folders or global config | No writes outside `<repo-root>` | met |
| Audit prior global Codex bootstrap | `agent-reports/codex-bootstrap-auditor.md` | met |
| Verify current Codex CLI behavior | `agent-reports/codex-cli-researcher.md`, local `codex --version`, `codex debug` checks, official OpenAI docs URLs | met |
| Create reusable bootstrap-pack structure | `_localsetup/docs/bootstrap-packs/INDEX.md`, `codex-agent-team/metadata.yaml`, `AUDIT_PROMPT.md`, and `pack.yaml` bootstrap pack | met |
| Target OpenAI Codex first while leaving room for later frameworks | `metadata.yaml` has `primary_platform: codex` and future platform list | met |
| Deterministic remediation plan | `REMEDIATION_PLAN.md` and `REMEDIATION_TASKS.yaml` | met |
| Safe legacy replacement workflow | `agent-reports/legacy-inventory.md`, remediation phase 3, tasks `REM-005` and `REM-006` | met |
| Documentation artifacts organized and indexed | `_localsetup/docs/README.md`, `_localsetup/docs/AGENTIC_DESIGN_INDEX.md`, generated pack map and file map | met |
| Bootstrap-pack index/metadata present | `_localsetup/docs/bootstrap-packs/INDEX.md`, `_localsetup/docs/bootstrap-packs/codex-agent-team/metadata.yaml` | met |
| Internally validated | Catalog, parse checks, bootstrap membership check, generated docs, diff check, changed-link check, framework audit, smoke tests, pytest, and final review passed | met |

## Known Limits

- No global Codex files were changed.
- No legacy trees were replaced.
- Custom-agent TOML schema remains partly source-inferred because no complete public schema page was found.
- Goal mode remains drift-prone based on current research.
