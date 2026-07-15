"""File and terminal helpers for tmux terminal mode."""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from .constants import BAK_SUFFIX, SENTINEL_BEGIN, SENTINEL_END


def die(msg: str, code: int = 1) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(code)


def warn(msg: str) -> None:
    print(f"[WARN]  {msg}", file=sys.stderr)


def info(msg: str) -> None:
    print(f"[INFO]  {msg}")


def ok(msg: str) -> None:
    print(f"[OK]    {msg}")


def dry(msg: str) -> None:
    print(f"[DRY]   {msg}")


def has_sentinel(text: str) -> bool:
    return SENTINEL_BEGIN in text


def strip_sentinel_block(text: str) -> str:
    pattern = re.compile(
        r"\n?" + re.escape(SENTINEL_BEGIN) + r".*?" + re.escape(SENTINEL_END) + r"\n?",
        re.DOTALL,
    )
    return pattern.sub("", text)


def safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        die(f"Cannot read {path}: {exc}")


def atomic_write(path: Path, content: str) -> None:
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        die(f"Failed to write {path}: {exc}")


def backup(path: Path, dry_run: bool) -> Path:
    bak = path.with_suffix(path.suffix + BAK_SUFFIX)
    if bak.exists():
        return bak
    if dry_run:
        dry(f"Would back up {path} -> {bak}")
        return bak
    try:
        shutil.copy2(str(path), str(bak))
        info(f"Backed up {path} -> {bak}")
    except OSError as exc:
        die(f"Could not back up {path}: {exc}")
    return bak


def restore_or_strip(path: Path, dry_run: bool, label: str) -> None:
    bak = path.with_suffix(path.suffix + BAK_SUFFIX)
    if bak.exists():
        if dry_run:
            dry(f"Would restore {label} from backup: {bak} -> {path}")
        else:
            try:
                shutil.copy2(str(bak), str(path))
                bak.unlink()
                ok(f"Restored {label} from backup: {path}")
            except OSError as exc:
                die(f"Could not restore {path} from backup: {exc}")
        return

    if not path.exists():
        info(f"Nothing to do for {label} ({path} not found).")
        return

    text = safe_read(path)
    if not has_sentinel(text):
        info(f"Nothing to do for {label} (no sentinel block found in {path}).")
        return

    stripped = strip_sentinel_block(text)
    if dry_run:
        dry(f"Would remove sentinel block from {label}: {path}")
    else:
        atomic_write(path, stripped)
        ok(f"Removed sentinel block from {label}: {path}")
