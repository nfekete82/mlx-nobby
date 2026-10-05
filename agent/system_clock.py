"""Fresh host-local time context for user-facing model turns."""

from __future__ import annotations

from datetime import datetime


def _utc_offset(value: datetime) -> str:
    raw = value.strftime("%z")
    if len(raw) == 5:
        return raw[:3] + ":" + raw[3:]
    return raw or "+00:00"


def snapshot(now: datetime | None = None) -> dict[str, str]:
    """Return one timezone-aware snapshot of the macOS host clock.

    ``now`` exists only for deterministic tests. Production callers omit it so
    every turn reads the current host clock and current local timezone/DST.
    """
    current = now if now is not None else datetime.now().astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.astimezone()

    return {
        "iso": current.isoformat(timespec="seconds"),
        "date": current.date().isoformat(),
        "time": current.strftime("%H:%M:%S"),
        "timezone": current.tzname() or "local",
        "utc_offset": _utc_offset(current),
    }


def context(now: datetime | None = None) -> str:
    """Build an authoritative, ephemeral system-time instruction for a turn."""
    value = snapshot(now)
    return (
        "CURRENT HOST SYSTEM TIME\n\n"
        f"- Local datetime: {value['iso']}\n"
        f"- Local date: {value['date']}\n"
        f"- Local time: {value['time']}\n"
        f"- Timezone: {value['timezone']}\n"
        f"- UTC offset: {value['utc_offset']}\n\n"
        "Rules:\n"
        "- Treat this host system time as authoritative for the current turn.\n"
        "- Use it for today, tomorrow, yesterday, this year, weekdays, ages, deadlines, and other relative date/time calculations.\n"
        "- Do not infer the current date or time from model training data or stale conversation text."
    )
