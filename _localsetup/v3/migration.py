from __future__ import annotations

from pathlib import Path
import shutil
from datetime import datetime, timezone

from .adapters import adapter_targets
from .aliases import collect_skill_aliases
from .lockfile import save_json
from .manifests import load_pack_config
from .paths import expand_user_path


DEFAULT_SCAN_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".sh", ".py", ".ps1"}
SKIP_DIRS = {".git", ".git-state-snapshots", ".venv", "__pycache__", "node_modules"}
RUNTIME_SKIP_PREFIXES = {
    (".codex", "runs"),
    ("state", "codex-heartbeat"),
    ("state", "repo-finalizer"),
    (".localsetup", "state", "codex-heartbeat"),
    (".localsetup", "state", "repo-finalizer"),
}


def _is_runtime_skip_path(rel: Path) -> bool:
    return any(rel.parts[: len(prefix)] == prefix for prefix in RUNTIME_SKIP_PREFIXES)


def scan_legacy_references(repo_root: Path, needle: str = "localsetup-") -> list[dict]:
    findings: list[dict] = []
    legacy_skill_names = set(collect_skill_aliases(repo_root / "_localsetup" / "skills"))
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in DEFAULT_SCAN_SUFFIXES:
            continue
        rel = path.relative_to(repo_root)
        if _is_runtime_skip_path(rel):
            continue
        if rel.parts[:2] == ("_localsetup", "skills"):
            continue
        if rel.parts[:2] == ("_localsetup", "tests"):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(lines, start=1):
            if needle in line:
                if legacy_skill_names and not any(name in line for name in legacy_skill_names):
                    continue
                findings.append({"path": str(rel), "line": line_no, "text": line.strip()[:240]})
    return findings


def _artifact(kind: str, path: Path, managed: bool, details: dict | None = None) -> dict:
    return {"kind": kind, "path": str(path), "managed": managed, "details": details or {}}


def detect_legacy_artifacts(
    repo_root: Path,
    *,
    home: Path,
    platform_ids: list[str] | None = None,
    target_root: Path | None = None,
) -> list[dict]:
    artifacts: list[dict] = []
    pack = load_pack_config(repo_root)
    global_root = expand_user_path(pack.global_root, home)
    attachment_root = target_root or repo_root

    skills_root = repo_root / "_localsetup" / "skills"
    if skills_root.exists():
        for path in sorted(skills_root.glob("localsetup-*")):
            artifacts.append(_artifact("legacy_source_skill", path, False))

    if global_root.exists():
        for path in sorted(global_root.glob("localsetup-*")):
            artifacts.append(_artifact("legacy_global_skill", path, (path / ".localsetup-managed").exists()))

    for target in adapter_targets(repo_root, home, platform_ids=platform_ids, target_root=attachment_root):
        path = target["repo_path"]
        if not (path.exists() or path.is_symlink()):
            continue
        if path.is_dir() and not path.is_symlink() and not (path / ".localsetup-portable").exists():
            artifacts.append(_artifact("unmanaged_adapter", path, False, {"platform": target["platform"]}))

    for rel in [".deps-missing", "_localsetup/.deps-missing", "_localsetup/tools/deploy", "_localsetup/tools/deploy.py", "_localsetup/tools/deploy.ps1"]:
        path = repo_root / rel
        if path.exists() or path.is_symlink():
            artifacts.append(_artifact("legacy_runtime_file", path, False))

    lock_path = attachment_root / "localsetup.lock.json"
    if lock_path.exists():
        artifacts.append(_artifact("lockfile", lock_path, True))

    return artifacts


def _backup_path(backup_root: Path, source: Path, repo_root: Path) -> Path:
    try:
        rel = source.resolve(strict=False).relative_to(repo_root.resolve(strict=False))
        return backup_root / "repo" / rel
    except ValueError:
        safe = str(source).strip("/").replace("/", "__")
        return backup_root / "external" / safe


def _backup_item(source: Path, backup_root: Path, repo_root: Path) -> str:
    dest = _backup_path(backup_root, source, repo_root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        dest.write_text(f"symlink -> {source.readlink()}\n", encoding="utf-8")
    elif source.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest, symlinks=True)
    elif source.exists():
        shutil.copy2(source, dest)
    return str(dest)


def conservative_migrate(
    repo_root: Path,
    *,
    home: Path,
    platform_ids: list[str] | None = None,
    target_root: Path | None = None,
    backup_dir: Path | None = None,
    apply: bool = True,
) -> dict:
    aliases = collect_skill_aliases(repo_root / "_localsetup" / "skills")
    pack = load_pack_config(repo_root)
    global_root = expand_user_path(pack.global_root, home)
    attachment_root = target_root or repo_root
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = backup_dir or (repo_root / ".localsetup" / "backups" / f"migration-{stamp}")
    resolved_backup = backup_root.resolve(strict=False)
    for target in adapter_targets(repo_root, home, platform_ids=platform_ids, target_root=attachment_root):
        adapter_root = target["repo_path"].resolve(strict=False)
        try:
            resolved_backup.relative_to(adapter_root)
        except ValueError:
            continue
        raise RuntimeError(f"backup directory must not be inside an adapter path: {backup_root}")

    artifacts = detect_legacy_artifacts(repo_root, home=home, platform_ids=platform_ids, target_root=attachment_root)
    blockers: list[dict] = []
    migrated: list[dict] = []
    backed_up: list[str] = []

    for artifact in artifacts:
        path = Path(artifact["path"])
        if artifact["kind"] in {"unmanaged_adapter", "legacy_source_skill", "legacy_runtime_file"}:
            blockers.append(
                {
                    "path": artifact["path"],
                    "kind": artifact["kind"],
                    "reason": "unmanaged path requires human review",
                    "remediation": f"mv {artifact['path']} {artifact['path']}.bak",
                }
            )

    if blockers:
        report = {
            "ok": False,
            "applied": False,
            "backup_dir": str(backup_root),
            "artifacts": artifacts,
            "migrated": migrated,
            "backed_up": backed_up,
            "blockers": blockers,
        }
        if apply:
            backup_root.mkdir(parents=True, exist_ok=True)
            save_json(backup_root / "migration-report.json", report)
        return report

    if not apply:
        return {
            "ok": True,
            "applied": False,
            "backup_dir": str(backup_root),
            "artifacts": artifacts,
            "migrated": migrated,
            "backed_up": backed_up,
            "blockers": blockers,
        }

    backup_root.mkdir(parents=True, exist_ok=True)
    for artifact in artifacts:
        path = Path(artifact["path"])
        if not (path.exists() or path.is_symlink()):
            continue
        backed_up.append(_backup_item(path, backup_root, repo_root))

        if artifact["kind"] == "legacy_global_skill" and path.name in aliases:
            dest = path.with_name(aliases[path.name])
            if dest.exists() and not (dest / ".localsetup-managed").exists():
                blockers.append(
                    {
                        "path": str(dest),
                        "kind": "global_skill_collision",
                        "reason": "destination skill exists and is unmanaged",
                        "remediation": f"mv {dest} {dest}.bak",
                    }
                )
                continue
            if dest.exists() or dest.is_symlink():
                if dest.is_dir() and not dest.is_symlink():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            path.rename(dest)
            (dest / ".localsetup-managed").write_text(f"source={dest.name}\n", encoding="utf-8")
            migrated.append({"from": str(path), "to": str(dest), "kind": artifact["kind"]})

    report = {
        "ok": not blockers,
        "applied": True,
        "backup_dir": str(backup_root),
        "artifacts": artifacts,
        "migrated": migrated,
        "backed_up": backed_up,
        "blockers": blockers,
    }
    save_json(backup_root / "migration-report.json", report)
    return report
