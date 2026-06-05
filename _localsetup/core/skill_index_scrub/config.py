from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from .constants import CTRL_RE, MAX_FIELD_LEN


def sanitize(value: str, max_len: int = MAX_FIELD_LEN) -> str:
    """Strip control chars, collapse whitespace, truncate."""
    if not value:
        return ""
    cleaned = CTRL_RE.sub("", value)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned[:max_len] if max_len else cleaned


def parse_index_updated(value: object) -> Optional[datetime]:
    """Parse PUBLIC_SKILL_INDEX.yaml updated values into UTC datetimes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_age(days: int) -> str:
    if days < 14:
        unit = "day" if days == 1 else "days"
        return f"{days} {unit}"
    if days < 365:
        weeks = days // 7
        unit = "week" if weeks == 1 else "weeks"
        return f"{weeks} {unit}"
    years = days // 365
    unit = "year" if years == 1 else "years"
    return f"{years} {unit}"


def index_refresh_status(updated: object, now: datetime) -> tuple[str, Optional[int], bool]:
    """Return display text, age in days, and whether the index is stale."""
    parsed = parse_index_updated(updated)
    if parsed is None:
        if updated:
            raw = sanitize(str(updated), max_len=120)
            return f"unparseable ({raw})", None, True
        return "missing / never refreshed", None, True

    age_days = (now.date() - parsed.date()).days
    if age_days < 0:
        future_days = abs(age_days)
        unit = "day" if future_days == 1 else "days"
        return f"{parsed.strftime('%Y-%m-%d')} ({future_days} {unit} in the future)", age_days, True
    return f"{parsed.strftime('%Y-%m-%d')} ({format_age(age_days)} ago)", age_days, age_days >= 7
