from __future__ import annotations

import os
import re
from collections import namedtuple
from pathlib import Path

DEFAULT_SEND_DELAY = 0.5
MAX_CMD_LEN = 32768

FAST_POLL_INTERVAL = 0.05
FAST_PHASE_DURATION = 2.0
MED_POLL_INTERVAL = 0.3
MED_PHASE_DURATION = 15.0
SLOW_POLL_INTERVAL = 1.0
DEFAULT_WAIT_TIMEOUT = 30.0
DEFAULT_RUN_TIMEOUT = 3600.0
DEFAULT_TAIL_LINES = 120

DEFAULT_IDLE_RE_STR = r"^.*[$#]\s*$"
IDLE_PROMPT_RE = re.compile(os.environ.get("TMUX_OPS_IDLE_RE", DEFAULT_IDLE_RE_STR))
PASSWORD_PROMPT_RE = re.compile(r"\[sudo\]\s*password\s+for|password.*:", re.I)

TmuxResult = namedtuple("TmuxResult", ("returncode", "stdout", "stderr"))

OPS_BASE = "ops"
SESSION_PATTERN = re.compile(r"^ops(\d*)$")
MAX_SESSION_NUM = 20

STATE_ROOT = Path(os.environ.get("TMUX_OPS_STATE_ROOT", "/tmp/localsetup-tmux-ops"))
WAIT_PREFIX = "localsetup-tmux-ops"

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
