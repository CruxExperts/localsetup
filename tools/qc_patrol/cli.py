from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.qc_patrol.chunking import chunk_text
from tools.qc_patrol.config import load_config
from tools.qc_patrol.deterministic_checks import run_deterministic
from tools.qc_patrol.diff_reader import fetch_ref, read_diff
from tools.qc_patrol.docs_drift import docs_alignment_findings
from tools.qc_patrol.issue_writer import write_issues
from tools.qc_patrol.ledger import build_ledger, write_json
from tools.qc_patrol.llm_client import LLMClient, LLMDisabled
from tools.qc_patrol.pr_writer import plan_autofix
from tools.qc_patrol.redaction import redact_text
from tools.qc_patrol.release_writer import release_readiness
from tools.qc_patrol.repo_inventory import build_inventory
from tools.qc_patrol.review_contracts import parse_strict_json


def build_pr_review_prompt(chunks: list[dict[str, object]], findings: list[dict[str, object]]) -> str:
    payload = {
        "task": "Review the supplied pull request diff chunks and deterministic findings for actionable repository QC issues.",
        "output_contract": {
            "format": "strict_json_only",
            "schema": {
                "findings": [
                    {
                        "category": "workflow_security|release|docs|pr_review|other_snake_case",
                        "severity": "low|medium|high|critical",
                        "title": "short finding title, max 140 characters",
                        "body": "concise rationale with evidence",
                        "affected_paths": ["path/from/repo/root"],
                        "region": "optional file region",
                        "check_type": "llm_pr_review",
                        "remediation": "optional suggested fix",
                    }
                ]
            },
            "empty_result": {"findings": []},
            "rules": [
                "Return only one JSON object.",
                "Do not wrap the JSON in markdown fences.",
                "Do not include prose before or after the JSON.",
                "If there are no actionable findings, return exactly {\"findings\":[]}.",
                "Do not include secrets, raw credentials, or endpoint URLs.",
            ],
        },
        "chunks": chunks,
        "deterministic_findings": findings,
    }
    return json.dumps(payload, sort_keys=True)


def _repo(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "repo", ".")).resolve()


def cmd_inventory(args: argparse.Namespace) -> int:
    write_json(Path(args.out), build_inventory(_repo(args)))
    return 0


def cmd_deterministic(args: argparse.Namespace) -> int:
    findings = run_deterministic(_repo(args), args.profile)
    write_json(Path(args.out), build_ledger("deterministic", findings, profile=args.profile))
    return 0


def cmd_pr_review(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    repo = Path(args.subject_repo).resolve()
    config = load_config(Path.cwd())
    if args.base_remote:
        fetch_ref(repo, args.base_remote, args.base)
    diff = read_diff(repo, args.base, args.head)
    chunks = chunk_text("pr-diff", diff, config.max_chunk_bytes)
    findings = run_deterministic(repo, "ci")
    if args.llm_mode != "off":
        try:
            response = LLMClient(config.llm).complete(build_pr_review_prompt(chunks, findings))
            findings.extend(parse_strict_json(response, out / "llm-raw-response.json").get("findings", []))
        except LLMDisabled:
            pass
        except Exception as exc:
            write_json(out / "llm-error.json", {"error": redact_text(str(exc)), "endpoint_alias": config.llm.endpoint_alias})
    write_json(out / "ledger.json", build_ledger("pr-review", findings, chunk_count=len(chunks), llm_mode=args.llm_mode))
    return 0


def cmd_patrol(args: argparse.Namespace) -> int:
    repo = _repo(args)
    out = Path(args.out)
    findings = run_deterministic(repo, "ci")
    issue_results = write_issues(findings, load_config(repo).labels, dry_run=not args.write_issues) if findings else []
    write_json(out / "ledger.json", build_ledger("patrol", findings, issue_results=issue_results))
    return 0


def cmd_docs_drift(args: argparse.Namespace) -> int:
    repo = _repo(args)
    findings = run_deterministic(repo, "docs")
    findings.extend(docs_alignment_findings(repo))
    issue_results = write_issues(findings, load_config(repo).labels, dry_run=not args.write_issues) if findings else []
    write_json(Path(args.out) / "ledger.json", build_ledger("docs-drift", findings, issue_results=issue_results))
    return 0


def cmd_release_readiness(args: argparse.Namespace) -> int:
    result = release_readiness(_repo(args), Path(args.out))
    write_json(Path(args.out) / "ledger.json", build_ledger("release-readiness", result["findings"], release=result))
    return 0 if result["package_returncode"] == 0 and result["verify_returncode"] == 0 else 1


def cmd_autofix(args: argparse.Namespace) -> int:
    result = plan_autofix(args.issue, dry_run=args.dry_run == "true", create_pr=args.create_pr == "true", out=Path(args.out))
    write_json(Path(args.out) / "ledger.json", build_ledger("autofix", [], autofix=result))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Localsetup GitHub QC patrol")
    sub = parser.add_subparsers(required=True)
    inventory = sub.add_parser("inventory")
    inventory.add_argument("--repo", default=".")
    inventory.add_argument("--out", required=True)
    inventory.set_defaults(func=cmd_inventory)
    deterministic = sub.add_parser("deterministic")
    deterministic.add_argument("--repo", default=".")
    deterministic.add_argument("--profile", choices=["ci", "docs", "release"], required=True)
    deterministic.add_argument("--out", required=True)
    deterministic.set_defaults(func=cmd_deterministic)
    pr_review = sub.add_parser("pr-review")
    pr_review.add_argument("--subject-repo", required=True)
    pr_review.add_argument("--base", required=True)
    pr_review.add_argument("--head", required=True)
    pr_review.add_argument("--base-remote", default="")
    pr_review.add_argument("--out", required=True)
    pr_review.add_argument("--llm-mode", choices=["auto", "off"], default="auto")
    pr_review.set_defaults(func=cmd_pr_review)
    for name, func in [("patrol", cmd_patrol), ("docs-drift", cmd_docs_drift)]:
        command = sub.add_parser(name)
        command.add_argument("--repo", default=".")
        command.add_argument("--out", required=True)
        command.add_argument("--write-issues", action="store_true")
        command.set_defaults(func=func)
    release = sub.add_parser("release-readiness")
    release.add_argument("--repo", default=".")
    release.add_argument("--out", required=True)
    release.set_defaults(func=cmd_release_readiness)
    autofix = sub.add_parser("autofix")
    autofix.add_argument("--issue", required=True)
    autofix.add_argument("--dry-run", choices=["true", "false"], required=True)
    autofix.add_argument("--create-pr", choices=["true", "false"], required=True)
    autofix.add_argument("--out", required=True)
    autofix.set_defaults(func=cmd_autofix)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
