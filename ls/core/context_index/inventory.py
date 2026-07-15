import fnmatch
from pathlib import Path
from typing import Any

from .common import DEFAULT_EXCLUDES, HIGH_PRIORITY_PATTERNS, Runtime
from .config import scope_definition

def rel_path(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.expanduser().resolve().as_posix()


def matches_any(value: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern == "**/*" and value:
            return True
        if fnmatch.fnmatch(value, pattern) or fnmatch.fnmatch(Path(value).name, pattern):
            return True
    return False


def is_excluded(rel: str, excludes: list[str]) -> bool:
    normalized = rel.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in {".git", "node_modules", "__pycache__", ".venv", "venv"} for part in parts):
        return True
    return matches_any(normalized, excludes)


def priority_for(rel: str) -> str:
    return "high" if matches_any(rel, HIGH_PRIORITY_PATTERNS) else "normal"


def source_type_for(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower().lstrip(".")
    if path.name == "SKILL.md":
        return "skill", "text"
    if suffix in {"md", "mdx", "rst", "txt"}:
        return "doc", "text"
    if suffix in {"json", "yaml", "yml", "toml", "ini"}:
        return "config", "text"
    if suffix in {"html", "htm", "xml", "css", "scss"}:
        return "markup", "text"
    if suffix in {"png", "jpg", "jpeg", "webp", "gif"}:
        return "image", "image"
    if suffix in {"py", "js", "jsx", "ts", "tsx", "java", "go", "rs", "c", "cpp", "h", "cs", "php", "rb", "swift", "kt", "sql", "sh", "bash", "zsh", "ps1"}:
        return "code", "code"
    return "other", "text"


def inventory(rt: Runtime, include_excluded: bool = False) -> list[dict[str, Any]]:
    definition = scope_definition(rt, rt.scope)
    roots = definition.get("roots") or ["."]
    includes = [str(v) for v in definition.get("include", ["**/*"])]
    excludes = [str(v) for v in definition.get("exclude", DEFAULT_EXCLUDES)]
    max_bytes = int(definition.get("max_file_bytes", 1048576))
    found: dict[str, dict[str, Any]] = {}
    for root_value in roots:
        root = Path(str(root_value)).expanduser()
        base = root if root.is_absolute() else rt.repo_root / root
        if not base.exists():
            continue
        paths = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
        for path in paths:
            rel = rel_path(rt.repo_root, path)
            excluded = is_excluded(rel, excludes)
            included = matches_any(rel, includes) or any(fnmatch.fnmatch(path.name, pat) for pat in includes)
            if not included and not (include_excluded and excluded):
                continue
            if excluded and not include_excluded:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size > max_bytes:
                if include_excluded:
                    found[rel] = {"path": rel, "status": "excluded", "reason": "max_file_bytes", "size": stat.st_size}
                continue
            source_type, modality = source_type_for(path)
            found[rel] = {
                "path": rel,
                "absolute": str(path.resolve()),
                "status": "included" if not excluded else "excluded",
                "reason": None if not excluded else "exclude_pattern",
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "priority": priority_for(rel),
                "source_type": source_type,
                "modality": modality,
            }
    return sorted(found.values(), key=lambda item: (0 if item.get("priority") == "high" else 1, item["path"]))
