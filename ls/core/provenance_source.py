from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path

from .git_subprocess import run_git
from .source import source_commit

GENERATED_SOURCE_DIRTY_PATHS = {
    "assets/README.md",
    "ls/docs/SKILLS.md",
    "ls/docs/WORKFLOW_QUICK_REF.md",
    "ls/docs/WORKFLOW_REGISTRY.md",
    "ls/docs/migration/skill-alias-map.md",
}
GENERATED_SOURCE_DIRTY_PREFIXES = (
    "ls/docs/_generated/",
)
GENERATED_RECEIPT_PATHS = {
    "README.md",
    "ls/docs/FEATURES.md",
    "ls/docs/README.md",
}
FACTS_BLOCK_START = "<!-- facts-block:start -->"
FACTS_BLOCK_END = "<!-- facts-block:end -->"
VERSION_SYNC_SUBJECT_PREFIX = "chore: sync release version "
GENERATED_DOCS_SUBJECT_PREFIX = "docs: refresh "


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_tree_sha(repo_root: Path) -> str:
    return tree_sha_for_ref(repo_root, "HEAD")


def tree_sha_for_ref(repo_root: Path, ref: str) -> str:
    completed = run_git(
        repo_root,
        ["rev-parse", f"{ref}^{{tree}}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip()


def git_text(repo_root: Path, args: list[str]) -> str | None:
    completed = run_git(
        repo_root,
        args,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def source_tag_for_ref(repo_root: Path, ref: str) -> str | None:
    return git_text(repo_root, ["describe", "--tags", "--exact-match", ref])


def status_entry_paths(line: str) -> list[str]:
    if len(line) < 4:
        return []
    path = line[3:].strip()
    if " -> " in path:
        return [part.strip() for part in path.split(" -> ", 1)]
    return [path]


def is_generated_output_path(path: str) -> bool:
    normalized = path.strip().strip('"')
    return normalized in GENERATED_SOURCE_DIRTY_PATHS or any(
        normalized.startswith(prefix) for prefix in GENERATED_SOURCE_DIRTY_PREFIXES
    )


def is_generated_receipt_path(path: str) -> bool:
    return path.strip().strip('"') in GENERATED_RECEIPT_PATHS


def _facts_block_bounds(lines: list[str]) -> tuple[int, int] | None:
    starts = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == FACTS_BLOCK_START]
    ends = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == FACTS_BLOCK_END]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        return None
    return starts[0], ends[0]


def _diff_is_within_facts_block(
    before: list[str],
    after: list[str],
) -> bool:
    before_bounds = _facts_block_bounds(before)
    after_bounds = _facts_block_bounds(after)
    if not before_bounds or not after_bounds:
        return False

    before_start, before_end = before_bounds
    after_start, after_end = after_bounds
    changed = False
    for tag, before_start_index, before_end_index, after_start_index, after_end_index in SequenceMatcher(
        a=before,
        b=after,
        autojunk=False,
    ).get_opcodes():
        if tag == "equal":
            continue
        changed = True
        if not (
            before_start < before_start_index <= before_end_index <= before_end
            and after_start < after_start_index <= after_end_index <= after_end
        ):
            return False
    return changed


def is_generated_facts_block_change(repo_root: Path, path: str) -> bool:
    """Whether an exact receipt path differs from HEAD only inside its facts block."""
    normalized = path.strip().strip('"')
    if normalized not in GENERATED_RECEIPT_PATHS:
        return False

    working_path = repo_root / normalized
    if not working_path.is_file():
        return False
    head = run_git(
        repo_root,
        ["show", f"HEAD:{normalized}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if head.returncode != 0:
        return False
    try:
        working_text = working_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return _diff_is_within_facts_block(
        head.stdout.splitlines(keepends=True),
        working_text.splitlines(keepends=True),
    )


def source_dirty(repo_root: Path) -> bool:
    completed = run_git(
        repo_root,
        ["status", "--porcelain", "--untracked-files=all"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return False
    for line in completed.stdout.splitlines():
        paths = status_entry_paths(line)
        if not paths:
            return True
        if all(is_generated_output_path(path) for path in paths):
            continue
        if len(paths) == 1 and is_generated_facts_block_change(repo_root, paths[0]):
            continue
        return True
    return False


def head_subject(repo_root: Path) -> str:
    return git_text(repo_root, ["log", "-1", "--pretty=%s"]) or ""


def subject_for_ref(repo_root: Path, ref: str) -> str | None:
    return git_text(repo_root, ["log", "-1", "--pretty=%s", ref])


def changed_paths_for_ref(repo_root: Path, ref: str) -> list[str]:
    output = git_text(repo_root, ["diff-tree", "--no-commit-id", "--name-only", "-r", ref])
    return [line for line in (output or "").splitlines() if line]


def release_sync_parent_dirty(repo_root: Path) -> bool:
    """Return the pre-commit dirty flag encoded by a generated release-sync commit."""
    if head_subject(repo_root).startswith(VERSION_SYNC_SUBJECT_PREFIX):
        return True
    if generated_docs_terminal_is_release_sync(repo_root, "HEAD"):
        return True
    merge_head_subject = subject_for_ref(repo_root, "HEAD^2")
    if merge_head_subject and merge_head_subject.startswith(VERSION_SYNC_SUBJECT_PREFIX):
        return True
    return generated_docs_terminal_is_release_sync(repo_root, "HEAD^2")


def generated_docs_terminal_ref(repo_root: Path, ref: str) -> str | None:
    current = ref
    subject = subject_for_ref(repo_root, current) or ""
    if not subject.startswith(GENERATED_DOCS_SUBJECT_PREFIX):
        return None

    while subject.startswith(GENERATED_DOCS_SUBJECT_PREFIX):
        changed_paths = changed_paths_for_ref(repo_root, current)
        if not changed_paths or any(
            not (is_generated_output_path(path) or is_generated_receipt_path(path))
            for path in changed_paths
        ):
            return None
        parent = git_text(repo_root, ["rev-parse", f"{current}^"])
        if not parent:
            return None
        current = parent
        subject = subject_for_ref(repo_root, current) or ""

    return current


def generated_docs_terminal_is_release_sync(repo_root: Path, ref: str) -> bool:
    terminal = generated_docs_terminal_ref(repo_root, ref)
    return bool(
        terminal
        and (subject_for_ref(repo_root, terminal) or "").startswith(VERSION_SYNC_SUBJECT_PREFIX)
    )


def generated_docs_source_ref(repo_root: Path, ref: str) -> str | None:
    terminal = generated_docs_terminal_ref(repo_root, ref)
    if not terminal:
        return None
    subject = subject_for_ref(repo_root, terminal) or ""
    if subject.startswith(VERSION_SYNC_SUBJECT_PREFIX):
        return git_text(repo_root, ["rev-parse", f"{terminal}^"])
    return terminal


def generated_artifact_parent_source_commit(repo_root: Path) -> str | None:
    """
    Generated artifact commits are produced from their parent source state.

    Without this, a clean CI regeneration rewrites committed provenance from the
    parent commit to the generated-docs commit itself, creating unavoidable drift.
    The parent mode is opt-in so package/install provenance still points at the
    actual current checkout.
    """
    subject = head_subject(repo_root)
    if subject.startswith(VERSION_SYNC_SUBJECT_PREFIX):
        return git_text(repo_root, ["rev-parse", "HEAD^"])
    if not subject.startswith(GENERATED_DOCS_SUBJECT_PREFIX):
        merge_head_subject = subject_for_ref(repo_root, "HEAD^2")
        if merge_head_subject is None:
            return None
        if merge_head_subject.startswith(VERSION_SYNC_SUBJECT_PREFIX):
            return git_text(repo_root, ["rev-parse", "HEAD^2^"])
        if generated_source := generated_docs_source_ref(repo_root, "HEAD^2"):
            return generated_source
        return None
    return generated_docs_source_ref(repo_root, "HEAD")


def source_remote_url(repo_root: Path) -> str | None:
    completed = run_git(
        repo_root,
        ["config", "--get", "remote.origin.url"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    if not value:
        return None
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value.removeprefix("git@github.com:")
    if value.endswith(".git"):
        value = value[:-4]
    return value.rstrip("/") or None


def framework_version(repo_root: Path) -> str:
    version_file = repo_root / "VERSION"
    if not version_file.exists():
        return "unknown"
    return version_file.read_text(encoding="utf-8").strip() or "unknown"


def source_root_id(repo_root: Path) -> str:
    seed = {
        "source_commit": source_commit(repo_root),
        "remote_url": source_remote_url(repo_root),
    }
    return _sha256_bytes(json.dumps(seed, sort_keys=True).encode("utf-8"))


def source_root_id_for_commit(repo_root: Path, commit: str) -> str:
    seed = {
        "source_commit": commit,
        "remote_url": source_remote_url(repo_root),
    }
    return _sha256_bytes(json.dumps(seed, sort_keys=True).encode("utf-8"))
