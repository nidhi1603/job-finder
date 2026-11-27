"""HTML-to-text and date helpers."""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone

_BLOCK = re.compile(r"(?i)<\s*(br|/p|/div|/li|/h[1-6]|/tr|/ul|/ol)\b[^>]*>")
_LI = re.compile(r"(?i)<\s*li\b[^>]*>")
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\r\f\v ]+")


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    s = html.unescape(raw) if "&lt;" in raw else raw
    s = _BLOCK.sub("\n", s)
    s = _LI.sub("\n- ", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    lines = [_SPACES.sub(" ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        try:
            dt = datetime.strptime(v[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def from_epoch_ms(ms: int | float | None) -> datetime | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


_POSTED_DAYS = re.compile(r"(\d+)\+?\s*days?\s*ago", re.I)


def parse_workday_posted(label: str, now: datetime) -> tuple[datetime | None, int | None]:
    """'Posted Today' / 'Posted Yesterday' / 'Posted 5 Days Ago' / 'Posted 30+ Days Ago' / 'Posted 2026-04-30'."""
    s = (label or "").lower()
    if "today" in s:
        days = 0
    elif "yesterday" in s:
        days = 1
    else:
        m = _POSTED_DAYS.search(s)
        if m:
            days = int(m.group(1)) + (1 if "+" in s else 0)
        else:
            dt = parse_iso(re.sub(r"[^0-9-]", "", s)) if re.search(r"\d{4}-\d{2}-\d{2}", s) else None
            if dt:
                return dt, (now - dt).days
            return None, None
    return now - timedelta(days=days), days
