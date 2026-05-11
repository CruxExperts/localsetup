from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ZERO_SHA = "0" * 40
VERSION_SYNC_PREFIX = "chore: sync release version"
RELEASE_TYPE_RE = re.compile(r"^Release-Type:\s*(major|minor|patch|none)\s*$", re.MULTILINE | re.IGNORECASE)
KNOWN_PATCH_TYPES = {
    "fix",
    "docs",
    "chore",
    "style",
    "refactor",
    "perf",
    "test",
    "ci",
    "build",
    "revert",
}
VERSIONED_DOC_GLOBS = (
    "_localsetup/docs/*.md",
)
INTERNAL_PATCH_PATHS = (
    ".githooks/",
    ".github/",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "README.md",
    "_localsetup/README.md",
    "_localsetup/docs/",
    "_localsetup/skills/ls-automatic-versioning/",
    "_localsetup/tests/",
)
RELEASE_TOOLING_PATHS = (
    "_localsetup/v3/cli.py",
    "_localsetup/v3/versioning.py",
)


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
        if not match:
            raise ValueError(f"invalid semantic version: {value!r}")
        return cls(*(int(part) for part in match.groups()))

    def bump(self, bump_type: str) -> "SemVer":
        if bump_type == "major":
            return SemVer(self.major + 1, 0, 0)
        if bump_type == "minor":
            return SemVer(self.major, self.minor + 1, 0)
        if bump_type == "patch":
            return SemVer(self.major, self.minor, self.patch + 1)
        if bump_type == "none":
            return self
        raise ValueError(f"unknown bump type: {bump_type}")

    @property
    def major_minor(self) -> str:
        return f"{self.major}.{self.minor}"

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    subject: str
    body: str


def _run_git(repo_root: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=check,
    )


def _git_text(repo_root: Path, args: list[str], *, check: bool = True) -> str:
    return _run_git(repo_root, args, check=check).stdout.strip()


def read_version(repo_root: Path, ref: str | None = None) -> SemVer:
    if ref:
        completed = _run_git(repo_root, ["show", f"{ref}:VERSION"], check=False)
        if completed.returncode == 0 and completed.stdout.strip():
            return SemVer.parse(completed.stdout.strip())
    return SemVer.parse((repo_root / "VERSION").read_text(encoding="utf-8").strip())


def default_base_ref(repo_root: Path) -> str:
    upstream = _run_git(repo_root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], check=False)
    if upstream.returncode == 0 and upstream.stdout.strip():
        return upstream.stdout.strip()
    remote_head = _run_git(repo_root, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], check=False)
    if remote_head.returncode == 0 and remote_head.stdout.strip():
        return remote_head.stdout.strip()
    return "origin/main"


def resolve_head(repo_root: Path, head: str | None = None) -> str:
    return _git_text(repo_root, ["rev-parse", head or "HEAD"])


def resolve_base(repo_root: Path, base: str | None = None, head: str | None = None) -> str:
    if base and base != ZERO_SHA:
        return _git_text(repo_root, ["rev-parse", base])
    if base == ZERO_SHA:
        merge_base = _run_git(repo_root, ["merge-base", default_base_ref(repo_root), head or "HEAD"], check=False)
        if merge_base.returncode == 0 and merge_base.stdout.strip():
            return merge_base.stdout.strip()
    return _git_text(repo_root, ["rev-parse", default_base_ref(repo_root)])


def list_commits(repo_root: Path, base: str, head: str) -> list[CommitInfo]:
    if base == head:
        return []
    raw = _run_git(repo_root, ["log", "--reverse", "--format=%H%x1f%s%x1f%b%x1e", f"{base}..{head}"]).stdout
    commits: list[CommitInfo] = []
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split("\x1f", 2)
        if len(parts) != 3:
            continue
        commits.append(CommitInfo(sha=parts[0], subject=parts[1], body=parts[2]))
    return commits


def classify_commit(subject: str, body: str = "") -> str:
    if subject.startswith("Merge "):
        return "none"
    if subject.startswith("Revert "):
        return "none"
    if subject.startswith(VERSION_SYNC_PREFIX):
        return "none"
    release_type = RELEASE_TYPE_RE.search(body)
    if release_type:
        return release_type.group(1).lower()
    if re.match(r"^[a-zA-Z]+(?:\([^)]+\))?!:", subject):
        return "major"
    if re.search(r"^BREAKING CHANGE:", body, flags=re.MULTILINE):
        return "major"
    match = re.match(r"^([a-zA-Z]+)(?:\([^)]+\))?:", subject)
    if not match:
        return "patch"
    commit_type = match.group(1).lower()
    if commit_type == "feat":
        return "minor"
    if commit_type in KNOWN_PATCH_TYPES:
        return "patch"
    return "patch"


def changed_files(repo_root: Path, sha: str) -> list[str]:
    output = _git_text(repo_root, ["diff-tree", "--no-commit-id", "--name-only", "-r", sha])
    return [line for line in output.splitlines() if line]


def _is_internal_patch_file(path: str) -> bool:
    return path in RELEASE_TOOLING_PATHS or any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in INTERNAL_PATCH_PATHS)


def classify_commit_for_release(repo_root: Path, commit: CommitInfo) -> str:
    base = classify_commit(commit.subject, commit.body)
    if base != "minor":
        return base
    release_type = RELEASE_TYPE_RE.search(commit.body)
    if release_type:
        return release_type.group(1).lower()
    files = changed_files(repo_root, commit.sha)
    if files and all(_is_internal_patch_file(path) for path in files):
        return "patch"
    return base


def bump_rank(bump_type: str) -> int:
    return {"none": 0, "patch": 1, "minor": 2, "major": 3}[bump_type]


def max_bump(bumps: Iterable[str]) -> str:
    result = "none"
    for bump in bumps:
        if bump_rank(bump) > bump_rank(result):
            result = bump
    return result


def _reverted_subject(subject: str) -> str | None:
    match = re.fullmatch(r'Revert "(.+)"', subject)
    if match:
        return match.group(1)
    return None


def net_unreleased_commits(commits: list[CommitInfo]) -> tuple[list[CommitInfo], list[dict[str, str]]]:
    remaining: list[CommitInfo] = []
    canceled: list[dict[str, str]] = []
    for commit in commits:
        reverted = _reverted_subject(commit.subject)
        if reverted:
            for index in range(len(remaining) - 1, -1, -1):
                original = remaining[index]
                if original.subject == reverted:
                    canceled.append(
                        {
                            "revert_sha": commit.sha,
                            "original_sha": original.sha,
                            "subject": reverted,
                        }
                    )
                    del remaining[index]
                    break
            else:
                remaining.append(commit)
            continue
        remaining.append(commit)
    return remaining, canceled


def plan_version(repo_root: Path, *, base: str | None = None, head: str | None = None, ref: str | None = None) -> dict:
    resolved_head = resolve_head(repo_root, head)
    resolved_base = resolve_base(repo_root, base, resolved_head)
    commits = list_commits(repo_root, resolved_base, resolved_head)
    net_commits, canceled = net_unreleased_commits(commits)
    bump = max_bump(classify_commit_for_release(repo_root, commit) for commit in net_commits)
    base_version = read_version(repo_root, resolved_base)
    target = base_version.bump(bump)
    current = read_version(repo_root, resolved_head)
    worktree = read_version(repo_root)
    version_sync_present = any(commit.subject.startswith(VERSION_SYNC_PREFIX) for commit in commits)
    ok = bump == "none" or current == target
    return {
        "ok": ok,
        "ref": ref,
        "base": resolved_base,
        "head": resolved_head,
        "base_version": str(base_version),
        "current_version": str(current),
        "worktree_version": str(worktree),
        "target_version": str(target),
        "major_minor": target.major_minor,
        "bump": bump,
        "version_sync_present": version_sync_present,
        "commit_count": len(commits),
        "net_commit_count": len(net_commits),
        "canceled_reverts": canceled,
        "commits": [
            {
                "sha": commit.sha,
                "subject": commit.subject,
                "bump": classify_commit_for_release(repo_root, commit),
                "raw_bump": classify_commit(commit.subject, commit.body),
                "files": changed_files(repo_root, commit.sha),
            }
            for commit in net_commits
        ],
    }


def _replace_regex(path: Path, pattern: str, replacement: str, *, flags: int = re.MULTILINE) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    new_text = re.sub(pattern, replacement, text, flags=flags)
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def _update_doc_frontmatter_versions(repo_root: Path, version: SemVer) -> list[str]:
    changed: list[str] = []
    for pattern in VERSIONED_DOC_GLOBS:
        for path in sorted(repo_root.glob(pattern)):
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---\n"):
                continue
            parts = text.split("---", 2)
            if len(parts) < 3:
                continue
            frontmatter = parts[1]
            new_frontmatter = re.sub(
                r'(?m)^version:\s*["\']?[0-9]+(?:\.[0-9]+){1,2}["\']?\s*$',
                f"version: {version.major_minor}",
                frontmatter,
            )
            if not new_frontmatter.endswith("\n"):
                new_frontmatter = f"{new_frontmatter}\n"
            new_text = f"---{new_frontmatter}---{parts[2]}"
            if new_text != text:
                path.write_text(new_text, encoding="utf-8")
                changed.append(str(path.relative_to(repo_root)))
    return changed


def sync_version_files(repo_root: Path, target_version: str) -> dict:
    target = SemVer.parse(target_version)
    changed: list[str] = []
    tracked_updates = [
        ("VERSION", lambda path: path.write_text(f"{target}\n", encoding="utf-8")),
    ]
    for rel_path, writer in tracked_updates:
        path = repo_root / rel_path
        before = path.read_text(encoding="utf-8") if path.exists() else None
        writer(path)
        after = path.read_text(encoding="utf-8")
        if before != after:
            changed.append(rel_path)

    replacements = [
        ("pyproject.toml", r'(?m)^version = "[0-9]+\.[0-9]+\.[0-9]+"$', f'version = "{target}"'),
        ("README.md", r"(?m)^\*\*Version:\*\* [0-9]+\.[0-9]+\.[0-9]+<br>$", f"**Version:** {target}<br>"),
        ("_localsetup/README.md", r"(?m)^\*\*Version:\*\* [0-9]+\.[0-9]+\.[0-9]+<br>$", f"**Version:** {target}<br>"),
        (
            "_localsetup/docs/VERSIONING.md",
            r"(?m)^- Current value: `[0-9]+\.[0-9]+\.[0-9]+`$",
            f"- Current value: `{target}`",
        ),
        (
            "uv.lock",
            r'(?m)(^\[\[package\]\]\nname = "localsetup"\nversion = ")[0-9]+\.[0-9]+\.[0-9]+(")',
            rf"\g<1>{target}\2",
        ),
    ]
    for rel_path, pattern, replacement in replacements:
        if _replace_regex(repo_root / rel_path, pattern, replacement):
            changed.append(rel_path)

    changed.extend(_update_doc_frontmatter_versions(repo_root, target))
    generator = repo_root / "_localsetup" / "tools" / "generate_docs_artifacts.py"
    subprocess.run(
        [sys.executable, str(generator), "--repo-root", str(repo_root)],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=True,
    )

    generated_paths = [
        "README.md",
        "_localsetup/docs/README.md",
        "_localsetup/docs/FEATURES.md",
        "_localsetup/docs/SKILLS.md",
        "_localsetup/docs/WORKFLOW_REGISTRY.md",
        "_localsetup/docs/WORKFLOW_QUICK_REF.md",
        "_localsetup/docs/_generated/facts.json",
        "_localsetup/docs/_generated/workflow-catalog.json",
    ]
    for rel_path in generated_paths:
        if rel_path not in changed:
            changed.append(rel_path)

    return {
        "version": str(target),
        "major_minor": target.major_minor,
        "changed_candidates": sorted(set(changed)),
    }


def check_version_files(repo_root: Path, target_version: str) -> dict:
    candidates = {
        repo_root / "VERSION",
        repo_root / "pyproject.toml",
        repo_root / "uv.lock",
        repo_root / "README.md",
        repo_root / "_localsetup" / "README.md",
        repo_root / "_localsetup" / "docs" / "VERSIONING.md",
        repo_root / "_localsetup" / "docs" / "README.md",
        repo_root / "_localsetup" / "docs" / "FEATURES.md",
        repo_root / "_localsetup" / "docs" / "SKILLS.md",
        repo_root / "_localsetup" / "docs" / "WORKFLOW_REGISTRY.md",
        repo_root / "_localsetup" / "docs" / "WORKFLOW_QUICK_REF.md",
        repo_root / "_localsetup" / "docs" / "_generated" / "facts.json",
        repo_root / "_localsetup" / "docs" / "_generated" / "workflow-catalog.json",
    }
    candidates.update((repo_root / "_localsetup" / "docs").glob("*.md"))
    before_contents = {
        path: path.read_text(encoding="utf-8") if path.exists() else None
        for path in candidates
    }
    before = _git_text(repo_root, ["status", "--porcelain"])
    before_diff = _run_git(repo_root, ["diff", "--name-only"], check=False).stdout.splitlines()
    before_staged = _run_git(repo_root, ["diff", "--cached", "--name-only"], check=False).stdout.splitlines()
    sync_version_files(repo_root, target_version)
    after = _git_text(repo_root, ["status", "--porcelain"])
    diff = _run_git(repo_root, ["diff", "--name-only"], check=False).stdout.splitlines()
    staged = _run_git(repo_root, ["diff", "--cached", "--name-only"], check=False).stdout.splitlines()
    ok = before == after and diff == before_diff and staged == before_staged
    for path, content in before_contents.items():
        if content is None:
            if path.exists():
                path.unlink()
            continue
        path.write_text(content, encoding="utf-8")
    return {
        "ok": ok,
        "dirty_before": before,
        "dirty_after": after,
        "diff_before": before_diff,
        "diff_after": diff,
        "staged_before": before_staged,
        "staged_after": staged,
    }


def stage_version_files(repo_root: Path) -> None:
    paths = [
        "VERSION",
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "_localsetup/README.md",
        "_localsetup/docs/VERSIONING.md",
        "_localsetup/docs/*.md",
        "_localsetup/docs/_generated/facts.json",
        "_localsetup/docs/_generated/workflow-catalog.json",
        "_localsetup/docs/SKILLS.md",
    ]
    _run_git(repo_root, ["add", *paths])


def commit_version_sync(repo_root: Path, target_version: str) -> str | None:
    stage_version_files(repo_root)
    staged = _git_text(repo_root, ["diff", "--cached", "--name-only"])
    if not staged:
        return None
    _run_git(repo_root, ["commit", "-m", f"{VERSION_SYNC_PREFIX} {target_version}"])
    return resolve_head(repo_root)


def push_lines_to_plans(repo_root: Path, lines: str) -> list[dict]:
    plans: list[dict] = []
    for raw_line in lines.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split()
        if len(parts) != 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = parts
        if local_sha == ZERO_SHA:
            continue
        plans.append(plan_version(repo_root, base=remote_sha, head=local_sha, ref=f"{local_ref}->{remote_ref}"))
    return plans


def print_json(payload: dict | list[dict]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
