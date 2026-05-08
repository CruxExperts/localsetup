#!/usr/bin/env python3
# Purpose: Deploy platform-specific context loaders and skills. Called by install.
# Supports both local (repo-local) and global (user-wide) deployment.
# Created: 2026-02-20
# Last updated: 2026-04-01

import argparse
import errno
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_ENGINE = Path(__file__).resolve().parents[1]
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))
from lib.path_resolution import get_engine_dir, get_project_root


def _safe_copy2(src: Path, dst: Path) -> None:
    """Copy file and metadata; on EPERM (e.g. overwriting root-owned dest), copy content only then optionally metadata."""
    try:
        shutil.copy2(src, dst)
    except (PermissionError, OSError) as e:
        if isinstance(e, OSError) and e.errno != errno.EPERM:
            raise
        # copy2/copy both fail on root-owned dest (utimes/chmod). Use content-only then best-effort metadata.
        shutil.copyfile(src, dst)
        try:
            shutil.copystat(src, dst)
        except (PermissionError, OSError) as meta_err:
            if isinstance(meta_err, OSError) and meta_err.errno != errno.EPERM:
                raise
            print(
                f"Warning: copied {dst.name} but could not set file metadata (permission denied).",
                file=sys.stderr,
            )


def _copy_tree_files(src_dir: Path, dest_dir: Path) -> None:
    """Copy a directory tree while skipping generated runtime/cache files."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in src_dir.rglob("*"):
        if not f.is_file():
            continue
        if "__pycache__" in f.parts or f.suffix == ".pyc" or f.suffix == ".log":
            continue
        rel = f.relative_to(src_dir)
        (dest_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        _safe_copy2(f, dest_dir / rel)


def _read_skill_frontmatter(skill_md: Path) -> dict:
    """Read the small YAML-like frontmatter subset used by shipped skills."""
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    meta: dict[str, object] = {}
    parent: str | None = None
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")) and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if value:
                meta[key] = value
                parent = None
            else:
                meta[key] = {}
                parent = key
        elif parent and ":" in line and isinstance(meta.get(parent), dict):
            key, value = line.split(":", 1)
            meta[parent][key.strip()] = value.strip().strip("\"'")
    return meta


def _write_agents_registry(root: Path, source: str) -> None:
    skills_dir = root / ".agents" / "skills"
    skills = []
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        meta = _read_skill_frontmatter(skill_md)
        metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
        skills.append(
            {
                "name": meta.get("name", skill_dir.name),
                "directory": skill_dir.name,
                "path": f"./.agents/skills/{skill_dir.name}/SKILL.md",
                "description": meta.get("description", ""),
                "version": metadata.get("version", "") if metadata else "",
                "sha256": hashlib.sha256(skill_md.read_bytes()).hexdigest(),
            }
        )
    registry = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "canonical_skills_path": "./.agents/skills",
        "source": source,
        "skill_count": len(skills),
        "skills": skills,
    }
    registry_path = root / ".agents" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")


def _deploy_repo_canonical_skills(engine_dir: Path, root: Path) -> Path:
    """Deploy repo-local skills once to the Codex-compatible canonical path."""
    skills_dir = root / ".agents" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    skills_src = engine_dir / "skills"
    for skill_dir in sorted(skills_src.glob("localsetup-*")):
        if skill_dir.is_dir():
            _copy_tree_files(skill_dir, skills_dir / skill_dir.name)
    try:
        source = f"./{skills_src.relative_to(root)}"
    except ValueError:
        source = str(skills_src)
    _write_agents_registry(root, source)
    return skills_dir


def _ensure_platform_skills_path(engine_dir: Path, root: Path, dest_dir: Path) -> None:
    """Point platform skill folders at .agents/skills when safe, otherwise sync."""
    canonical = _deploy_repo_canonical_skills(engine_dir, root)
    if dest_dir.resolve() == canonical.resolve():
        return
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    rel_target = os.path.relpath(canonical, dest_dir.parent)
    if dest_dir.is_symlink():
        if os.readlink(dest_dir) != rel_target:
            dest_dir.unlink()
            dest_dir.symlink_to(rel_target, target_is_directory=True)
        return
    if not dest_dir.exists():
        try:
            dest_dir.symlink_to(rel_target, target_is_directory=True)
            return
        except OSError:
            print(
                f"Warning: could not symlink {dest_dir} to {rel_target}; copying skills instead.",
                file=sys.stderr,
            )
    for skill_dir in sorted(canonical.glob("localsetup-*")):
        if skill_dir.is_dir():
            _copy_tree_files(skill_dir, dest_dir / skill_dir.name)


def deploy_cursor(engine_dir: Path, root: Path) -> None:
    rules_dir = root / ".cursor" / "rules"
    skills_dir = root / ".cursor" / "skills"
    rules_dir.mkdir(parents=True, exist_ok=True)
    templates = engine_dir / "templates" / "cursor"
    if (templates / "localsetup-context.mdc").exists():
        _safe_copy2(
            templates / "localsetup-context.mdc", rules_dir / "localsetup-context.mdc"
        )
        _safe_copy2(
            templates / "localsetup-context-index.md",
            rules_dir / "localsetup-context-index.md",
        )
    if (templates / "AGENT_MEMORY.md").exists():
        _safe_copy2(templates / "AGENT_MEMORY.md", rules_dir / "agent-memory.md")
    _ensure_platform_skills_path(engine_dir, root, skills_dir)


def deploy_kilo(engine_dir: Path, root: Path) -> None:
    kilo_dir = root / ".kilo"
    skills_dir = kilo_dir / "skills"
    command_dir = kilo_dir / "command"
    agent_dir = kilo_dir / "agent"
    kilo_dir.mkdir(parents=True, exist_ok=True)
    command_dir.mkdir(parents=True, exist_ok=True)
    agent_dir.mkdir(parents=True, exist_ok=True)
    templates = engine_dir / "templates" / "kilo"
    if (templates / "instructions.md").exists():
        _safe_copy2(templates / "instructions.md", kilo_dir / "instructions.md")
    if (templates / "AGENT_MEMORY.md").exists():
        _safe_copy2(templates / "AGENT_MEMORY.md", kilo_dir / "AGENT_MEMORY.md")
    _ensure_platform_skills_path(engine_dir, root, skills_dir)


def deploy_claude_code(engine_dir: Path, root: Path) -> None:
    claude_dir = root / ".claude"
    skills_dir = claude_dir / "skills"
    claude_dir.mkdir(parents=True, exist_ok=True)
    templates = engine_dir / "templates" / "claude-code"
    if (templates / "CLAUDE.md").exists():
        _safe_copy2(templates / "CLAUDE.md", claude_dir / "CLAUDE.md")
    if (templates / "AGENT_MEMORY.md").exists():
        _safe_copy2(templates / "AGENT_MEMORY.md", claude_dir / "AGENT_MEMORY.md")
    _ensure_platform_skills_path(engine_dir, root, skills_dir)


def deploy_codex(engine_dir: Path, root: Path) -> None:
    _deploy_repo_canonical_skills(engine_dir, root)
    _ensure_platform_skills_path(engine_dir, root, root / ".codex" / "skills")
    templates = engine_dir / "templates" / "codex"
    if (templates / "AGENTS.md").exists():
        _safe_copy2(templates / "AGENTS.md", root / "AGENTS.md")
    if (templates / "AGENT_MEMORY.md").exists():
        _safe_copy2(templates / "AGENT_MEMORY.md", root / ".agents" / "AGENT_MEMORY.md")


def deploy_openclaw(engine_dir: Path, root: Path) -> None:
    skills_dir = root / "skills"
    localsetup_base = root / "_localsetup"
    docs_dir = localsetup_base / "docs"
    skills_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    templates = engine_dir / "templates" / "openclaw"
    if (templates / "OPENCLAW_CONTEXT.md").exists():
        _safe_copy2(templates / "OPENCLAW_CONTEXT.md", docs_dir / "OPENCLAW_CONTEXT.md")
    if (templates / "AGENT_MEMORY.md").exists():
        _safe_copy2(templates / "AGENT_MEMORY.md", root / "AGENT_MEMORY.md")
    skills_src = engine_dir / "skills"
    for skill_dir in sorted(skills_src.glob("localsetup-*")):
        if skill_dir.is_dir():
            dest = skills_dir / skill_dir.name
            dest.mkdir(parents=True, exist_ok=True)
            for f in skill_dir.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(skill_dir)
                    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                    _safe_copy2(f, dest / rel)


def deploy_opencode(engine_dir: Path, root: Path) -> None:
    opencode_dir = root / ".opencode"
    skills_dir = opencode_dir / "skills"
    opencode_dir.mkdir(parents=True, exist_ok=True)
    templates = engine_dir / "templates" / "opencode"
    if (templates / "AGENTS.md").exists():
        _safe_copy2(templates / "AGENTS.md", root / "AGENTS.md")
    if (templates / "AGENT_MEMORY.md").exists():
        _safe_copy2(templates / "AGENT_MEMORY.md", opencode_dir / "AGENT_MEMORY.md")
    _ensure_platform_skills_path(engine_dir, root, skills_dir)


def _parse_jsonc(path: Path) -> dict:
    """Parse a JSONC file, stripping // and /* */ comments."""
    if not path.exists():
        return {}
    content = path.read_text()
    lines = content.split("\n")
    result_lines = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("//"):
            result_lines.append("")
        else:
            result_lines.append(line)
    content = "\n".join(result_lines)
    return json.loads(content) if content.strip() else {}


def _write_jsonc(path: Path, data: dict) -> None:
    """Write data to a JSONC file preserving some formatting."""
    content = json.dumps(data, indent=2)
    path.write_text(content + "\n")


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Deep merge overlay into base, modifying base in place and returning it."""
    for key, val in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        elif key in base and isinstance(base[key], list) and isinstance(val, list):
            for item in val:
                if item not in base[key]:
                    base[key].append(item)
        else:
            base[key] = val
    return base


def _expand_path(path_str: str) -> Path:
    """Expand ~ and environment variables in a path string."""
    return Path(os.path.expanduser(os.path.expandvars(path_str)))


def _get_kilo_config_path() -> Path:
    """Return the global kilo config path (kilo.jsonc)."""
    return _expand_path("~/.config/kilo/kilo.jsonc")


def _deploy_skills_to_dir(engine_dir: Path, dest_dir: Path) -> None:
    """Copy all localsetup-* skills to dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    skills_src = engine_dir / "skills"
    for skill_dir in sorted(skills_src.glob("localsetup-*")):
        if skill_dir.is_dir():
            _copy_tree_files(skill_dir, dest_dir / skill_dir.name)


def _ensure_kilo_config_instructions(
    config_path: Path, instructions_path: Path
) -> None:
    """Idempotently add instructions_path to instructions[] in kilo.json or kilo.jsonc if not already present."""
    config_path = _expand_path(str(config_path))
    if not config_path.exists():
        config_path.write_text('{\n  "instructions": []\n}\n')

    data = _parse_jsonc(config_path)
    instructions = data.get("instructions", [])
    instr_str = str(instructions_path)
    if instr_str not in instructions:
        instructions.append(instr_str)
        data["instructions"] = instructions
        _write_jsonc(config_path, data)


def deploy_kilo_global(engine_dir: Path) -> None:
    """Deploy skills and context to global kilo locations aligned with Kilo v1+ conventions.

    Skills go to ~/.config/kilo/skills/ which Kilo auto-discovers.
    Context (instructions) goes to ~/.config/kilo/instructions/localsetup.md.
    Config merge idempotently adds the instructions file to instructions[] in kilo.json/kilo.jsonc.
    """
    kilo_config_base = _expand_path("~/.config/kilo")
    skills_dir = kilo_config_base / "skills"
    instructions_dir = kilo_config_base / "instructions"

    kilo_config_base.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)
    instructions_dir.mkdir(parents=True, exist_ok=True)

    templates_kilo = engine_dir / "templates" / "kilo"
    if (templates_kilo / "instructions.md").exists():
        _safe_copy2(
            templates_kilo / "instructions.md",
            instructions_dir / "localsetup.md",
        )
    if (templates_kilo / "AGENT_MEMORY.md").exists():
        _safe_copy2(
            templates_kilo / "AGENT_MEMORY.md",
            kilo_config_base / "AGENT_MEMORY.md",
        )

    _deploy_skills_to_dir(engine_dir, skills_dir)

    config_path_json = _expand_path("~/.config/kilo/kilo.json")
    config_path_jsonc = _expand_path("~/.config/kilo/kilo.jsonc")
    if config_path_json.exists() or config_path_jsonc.exists():
        target_config = (
            config_path_json if config_path_json.exists() else config_path_jsonc
        )
        _ensure_kilo_config_instructions(
            target_config,
            instructions_dir / "localsetup.md",
        )
    else:
        _ensure_kilo_config_instructions(
            config_path_jsonc,
            instructions_dir / "localsetup.md",
        )


def deploy_openclaw_global(engine_dir: Path) -> None:
    """Deploy skills to global openclaw location (~/.openclaw/skills/)."""
    openclaw_dir = _expand_path("~/.openclaw")
    skills_dir = openclaw_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    templates = engine_dir / "templates" / "openclaw"
    context_src = templates / "OPENCLAW_CONTEXT.md"
    if context_src.exists():
        _safe_copy2(context_src, openclaw_dir / "OPENCLAW_CONTEXT.md")
    if (templates / "AGENT_MEMORY.md").exists():
        _safe_copy2(templates / "AGENT_MEMORY.md", openclaw_dir / "AGENT_MEMORY.md")

    _deploy_skills_to_dir(engine_dir, skills_dir)


def deploy_claude_code_global(engine_dir: Path) -> None:
    """Deploy skills and context to global claude-code location (~/.claude/)."""
    claude_dir = _expand_path("~/.claude")
    skills_dir = claude_dir / "skills"
    claude_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)

    templates = engine_dir / "templates" / "claude-code"
    if (templates / "CLAUDE.md").exists():
        _safe_copy2(templates / "CLAUDE.md", claude_dir / "CLAUDE.md")
    if (templates / "AGENT_MEMORY.md").exists():
        _safe_copy2(templates / "AGENT_MEMORY.md", claude_dir / "AGENT_MEMORY.md")

    _deploy_skills_to_dir(engine_dir, skills_dir)


def deploy_opencode_global(engine_dir: Path) -> None:
    """Deploy skills to global opencode location (~/.config/opencode/skills/)."""
    opencode_dir = _expand_path("~/.config/opencode")
    skills_dir = opencode_dir / "skills"
    opencode_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)

    templates = engine_dir / "templates" / "opencode"
    if (templates / "AGENT_MEMORY.md").exists():
        _safe_copy2(templates / "AGENT_MEMORY.md", opencode_dir / "AGENT_MEMORY.md")

    _deploy_skills_to_dir(engine_dir, skills_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description="Deploy platform context and skills.")
    ap.add_argument(
        "--root", default=None, help="Client repo root (default: derived from engine)"
    )
    ap.add_argument(
        "--tools",
        required=True,
        help="Comma-separated: cursor,claude-code,codex,openclaw,opencode,kilo",
    )
    ap.add_argument(
        "--scope",
        default="local",
        choices=["local", "global"],
        help="Deployment scope: local (repo-local) or global (user-wide). Default: local",
    )
    args = ap.parse_args()

    engine_dir = get_engine_dir()
    if args.root is not None:
        root = Path(args.root).resolve()
    else:
        root = get_project_root()

    tools_csv = [t.strip().lower() for t in args.tools.split(",") if t.strip()]
    deployers = {
        "cursor": deploy_cursor,
        "claude-code": deploy_claude_code,
        "codex": deploy_codex,
        "openclaw": deploy_openclaw,
        "opencode": deploy_opencode,
        "kilo": deploy_kilo,
    }
    global_deployers = {
        "kilo": deploy_kilo_global,
        "openclaw": deploy_openclaw_global,
        "claude-code": deploy_claude_code_global,
        "opencode": deploy_opencode_global,
    }

    if args.scope == "global":
        for t in tools_csv:
            if t in global_deployers:
                try:
                    global_deployers[t](engine_dir)
                except (OSError, PermissionError) as e:
                    print(f"Global deploy failed ({t}): {e}", file=sys.stderr)
                    print(
                        "Check permissions on the target directory and that no files are owned by another user or immutable.",
                        file=sys.stderr,
                    )
                    return 1
            elif t:
                print(f"Unknown tool for global deploy: {t}", file=sys.stderr)
        return 0

    for t in tools_csv:
        if t in deployers:
            try:
                deployers[t](engine_dir, root)
            except (OSError, PermissionError) as e:
                print(f"Deploy failed ({t}): {e}", file=sys.stderr)
                print(
                    "Check permissions on the target directory and that no files are owned by another user or immutable.",
                    file=sys.stderr,
                )
                return 1
        elif t:
            print(f"Unknown tool: {t}", file=sys.stderr)

    # Sync docs to _localsetup/docs (skip when engine is inside repo and dest is same as src)
    docs_src = engine_dir / "docs"
    if docs_src.is_dir():
        docs_dest = root / "_localsetup" / "docs"
        if docs_src.resolve() != docs_dest.resolve():
            docs_dest.mkdir(parents=True, exist_ok=True)
            try:
                for f in docs_src.rglob("*"):
                    if f.is_file():
                        rel = f.relative_to(docs_src)
                        (docs_dest / rel).parent.mkdir(parents=True, exist_ok=True)
                        _safe_copy2(f, docs_dest / rel)
            except (OSError, PermissionError) as e:
                print(f"Deploy failed (docs sync): {e}", file=sys.stderr)
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
