"""Release documentation command dispatch; mutations are explicit commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="localsetup release-docs")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("plan", "prepare", "apply", "render", "check", "notes"):
        command = sub.add_parser(name)
        command.add_argument("--base")
        command.add_argument("--head", default="HEAD")
        command.add_argument("--repair", action="store_true")
        command.add_argument("--version")
        command.add_argument("--verify-baseline", action="store_true")
        if name in ("prepare", "apply"):
            command.add_argument("--candidate", type=Path, required=True)
        if name == "check":
            command.add_argument("--draft-tag")
            command.add_argument("--expected-commit")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    try:
        from .content import load_record
        from .planning import plan
        from .github import git, published_baseline, check_draft, guard_repair

        if args.action in ("plan", "prepare", "apply"):
            baseline = None
            if args.verify_baseline:
                baseline = published_baseline(root, git(root, "rev-parse", args.head))
            payload = plan(root, base=baseline["commit"] if baseline else args.base,
                           head=args.head, repair=args.repair)
            if baseline:
                if args.repair and baseline["version"] != payload["target_version"]:
                    raise ValueError("Repair must target the current published release version")
                if args.repair:
                    guard_repair(root, baseline, payload["source_commit"])
                if not args.repair:
                    payload["baseline_tag"] = baseline["tag"]
                payload["published_baseline"] = baseline
            if args.action == "prepare":
                from .agent import prepare_candidate
                state = root / ".agents/state"
                if not args.candidate.resolve().is_relative_to(state.resolve()):
                    raise ValueError("Candidate evidence must remain in .agents/state")
                if git(root, "status", "--porcelain"):
                    raise ValueError("Prepare requires a clean checkout; no provider request was made")
                if not payload["ok"]:
                    raise ValueError("Release documentation plan has unresolved findings")
                from ..docs_alignment.audit import audit
                static = audit(root)
                payload["static_audit"] = {
                    "ok": static["ok"], "findings": static["findings"],
                    "documents": payload["documents"],
                }
                affected = {path for paths in payload["affected_documents"].values() for path in paths}
                affected.update(item.get("path", "") for item in static["findings"])
                affected.update({"README.md", "ls/README.md", "ls/docs/README.md"})
                payload["semantic_documents"] = sorted(affected.intersection(payload["documents"]))
                candidate = prepare_candidate(root, payload)
                args.candidate.parent.mkdir(parents=True, exist_ok=True)
                args.candidate.write_text(json.dumps({"plan": payload, "candidate": candidate}, indent=2) + "\n")
                payload = {"ok": True, "source_commit": payload["source_commit"], "review": candidate["review"]}
            elif args.action == "apply":
                from .application import apply_candidate
                saved = json.loads(args.candidate.read_text())
                if saved["plan"]["source_commit"] != payload["source_commit"]:
                    raise ValueError("Saved documentation candidate is stale")
                payload = apply_candidate(root, saved["plan"], saved["candidate"])
        else:
            version = args.version or (root / "VERSION").read_text().strip()
            record = load_record(root, version)
            if args.action == "render":
                from .render import render_outputs
                outputs = render_outputs(root, record)
                for relative, content in outputs.items():
                    destination = root / relative
                    if destination.is_symlink() or not destination.resolve().is_relative_to(root):
                        raise ValueError("Rendered path escapes source repository")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(content, encoding="utf-8")
                print(json.dumps({"ok": True, "rendered": sorted(outputs)}))
                return 0
            if args.action == "notes":
                from .render import notes
                from .safety import check_public_text
                text = notes(record)
                check_public_text(text)
                print(text, end="")
                return 0
            from .checks import check
            payload = check(root, record)
            if args.draft_tag:
                if not payload["ok"]:
                    raise ValueError("Local documentation checks must pass before draft validation")
                expected = args.expected_commit or git(root, "rev-parse", args.head)
                payload["draft"] = check_draft(root, args.draft_tag, record, expected)
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok") else 1
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}))
        return 1
