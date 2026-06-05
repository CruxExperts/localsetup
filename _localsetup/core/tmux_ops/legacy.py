from __future__ import annotations

import os
import re
import time
from typing import Any

from .constants import DEFAULT_SEND_DELAY, DEFAULT_WAIT_TIMEOUT, FAST_PHASE_DURATION, FAST_POLL_INTERVAL, IDLE_PROMPT_RE, MED_PHASE_DURATION, MED_POLL_INTERVAL, SLOW_POLL_INTERVAL
from .sanitize import _sanitize_command, _sanitize_session
from .tmux import _capture_line, _cursor_y, _snapshot_cursor, _targeted_tmux

def cmd_wait(
    target: str,
    timeout: float = DEFAULT_WAIT_TIMEOUT,
    idle_re: re.Pattern[str] | None = None,
    pre_cursor_y: int | None = None,
) -> dict[str, Any]:
    san = _sanitize_session(target)
    if san is None:
        return {"error": "invalid session name", "session": target, "source": "wait"}

    pattern = idle_re or IDLE_PROMPT_RE
    start = time.monotonic()
    polls = 0
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= timeout:
            cy, _ = _cursor_y(san)
            cursor_line = ""
            if cy is not None:
                cursor_line, _ = _capture_line(san, cy)
            return {
                "session": san,
                "idle": False,
                "elapsed_s": round(elapsed, 3),
                "polls": polls,
                "timed_out": True,
                "cursor_line": cursor_line,
            }
        interval = FAST_POLL_INTERVAL if elapsed < FAST_PHASE_DURATION else MED_POLL_INTERVAL if elapsed < MED_PHASE_DURATION else SLOW_POLL_INTERVAL
        time.sleep(interval)
        polls += 1
        cy, _ = _cursor_y(san)
        if cy is None:
            continue
        if pre_cursor_y is not None and cy == pre_cursor_y:
            continue
        line, _ = _capture_line(san, cy)
        if pattern.match(line):
            return {"session": san, "idle": True, "elapsed_s": round(time.monotonic() - start, 3), "polls": polls}


def cmd_send(
    target: str,
    command: str,
    delay: float | None = None,
    wait: bool = False,
    wait_timeout: float = DEFAULT_WAIT_TIMEOUT,
    idle_re: re.Pattern[str] | None = None,
) -> dict[str, Any]:
    san = _sanitize_session(target)
    if san is None:
        return {"error": "invalid session name", "session": target, "source": "send"}
    cmd, cmd_err = _sanitize_command(command)
    if cmd_err is not None:
        return {"error": "invalid command", "detail": cmd_err, "session": san, "source": "send"}
    if delay is None:
        try:
            delay = float(os.environ.get("TMUX_OPS_SEND_DELAY", str(DEFAULT_SEND_DELAY)))
        except ValueError:
            delay = DEFAULT_SEND_DELAY
    if delay < 0:
        return {"error": "delay must be non-negative", "detail": str(delay), "session": san, "source": "send"}
    pre_cy = _snapshot_cursor(san)
    r = _targeted_tmux(san, ["send-keys", "-t", "{target}", cmd, "Enter"])
    if r.returncode != 0:
        return {"error": "tmux send-keys failed", "detail": r.stderr, "session": san, "source": "send"}
    time.sleep(delay)
    result: dict[str, Any] = {"session": san, "sent": True, "delay_s": delay}
    if wait:
        w = cmd_wait(san, wait_timeout, idle_re, pre_cursor_y=pre_cy)
        result.update({k: v for k, v in w.items() if k != "session"})
    return result
