"""Conservative reference classification, independent of filesystem access."""

from __future__ import annotations

import hashlib
import re
import shlex


REFERENCE = re.compile(r"(?<![A-Za-z])(?:local[ _-]?setup|lscli)(?![A-Za-z])", re.IGNORECASE)
EXCEPTION_KINDS = {"compatibility_identifier", "upstream_attribution", "historical_evidence", "negative_test"}


def line_hash(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def classify(line: str, start: int, end: int) -> str:
    token = line[start:end]
    before, after = line[:start], line[end:]
    left = re.search(r"[A-Za-z0-9_./:@~+-]*$", before).group()
    right = re.match(r"[A-Za-z0-9_./:@~+-]*", after).group()
    word = left + token + right
    # Obvious URLs, filenames, and qualified paths. A display separator alone
    # (Product/CLI) and Markdown emphasis are deliberately ambiguous.
    if "://" in word or word.startswith(("/", "~/", "./", "../")):
        return "technical"
    if re.match(r"\.(?:py|md|json|yaml|toml|png|svg|whl|tar|gz)(?:$|[^A-Za-z])", right):
        return "technical"
    identifier = re.search(r"[A-Za-z0-9_]*$", before).group() + token + re.match(r"[A-Za-z0-9_]*", after).group()
    if re.fullmatch(r"[A-Z][A-Z0-9]*_[A-Z0-9_]+", identifier) and token == token.upper():
        return "technical"
    if token in {"localsetup", "lscli"}:
        if re.fullmatch(r"[A-Za-z0-9_./~-]+\.(?:py|md|json|yaml|yml|toml|png|svg|whl|tar|gz)", word):
            return "technical"
        if (left.endswith(("_", ".")) and left.strip("_.")) or (right.startswith("_") and right.strip("_")):
            return "technical"
        if left == "." or re.match(r"\.[a-z]", right):
            return "technical"
        if (len(before) > 1 and before[-1] == "-" and before[-2].isalnum()) or re.match(r"-v\d", after):
            return "technical"
        if before.endswith("`") and (after.startswith("`") or after.startswith(" ")):
            return "technical"
        if re.search(r"(?:import|from|python\s+-m|command\s+-v|which|exec|uv\s+run)\s+$", before):
            return "technical"
        if re.search(r"(?:name|package|distribution)\s*[=:]\s*['\"]$", before) and after[:1] in {"'", '"'}:
            return "technical"
        if after.startswith(":") or re.match(r"\s+--[a-z]", after):
            return "technical"
    if token in {"LocalSetup", "LSCli"}:
        return "canonical"
    return "unclassified"


def _shell_command_lines(lines: list[str]) -> set[int]:
    """Select simple fenced shell lines; ambiguous shell constructs stay scanned."""
    allowed: set[int] = set()
    fence, language, block = None, "", []
    for number, line in enumerate(lines, 1):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})([^`~]*)$", line)
        if fence is None:
            if marker:
                fence, language = marker.group(1), marker.group(2).strip()
                block = []
            continue
        if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) and not marker.group(2).strip():
            if language in {"bash", "sh", "shell", "console", "zsh"}:
                try:
                    for _, content in block:
                        if "<<" in content or content.rstrip().endswith("\\"):
                            raise ValueError("multiline shell construct")
                        shlex.split(content, comments=True)
                except ValueError:
                    pass  # Literal bodies cannot be distinguished without a shell parser.
                else:
                    allowed.update(n for n, content in block if language != "console" or re.match(r"^\s*[$>]\s+", content))
            fence = None
        else:
            block.append((number, line))
    return allowed


def references(path: str, text: str) -> list[dict]:
    rows = []
    lines = text.splitlines()
    shell_lines = _shell_command_lines(lines)
    for number, line in enumerate(lines, 1):
        for match in REFERENCE.finditer(line):
            classification = classify(line, match.start(), match.end())
            if (number in shell_lines and match.group() in {"localsetup", "lscli"}
                    and re.fullmatch(r"\s*(?:[$>]\s+)?", line[:match.start()])
                    and (not line[match.end():] or line[match.end()].isspace())):
                classification = "technical"
            rows.append({
                "path": path, "line": number, "column": match.start() + 1,
                "token": match.group(), "line_sha256": line_hash(line),
                "classification": classification,
            })
    return rows
