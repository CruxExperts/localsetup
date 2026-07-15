from __future__ import annotations

import re


TOOL_VERSION = "1.0.0"
TOOL_NAME = "skill_index_scrub"

MAX_DESC_LEN = 300
MIN_DESC_LEN_DEFAULT = 20
DEFAULT_WORKERS = 10
DEFAULT_TIMEOUT = 10
MAX_FIELD_LEN = 4096
HARD_DEAD_URL_STATUSES = {404, 410}

STUB_PATTERNS = (
    re.compile(r"^anthropic skill:", re.IGNORECASE),
    re.compile(r"^openclaw skill:", re.IGNORECASE),
    re.compile(r"^clawdhub skill:", re.IGNORECASE),
)

UPSTREAM_FILENAMES = ("SKILL.md", "README.md", "readme.md", "skill.md")

CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
