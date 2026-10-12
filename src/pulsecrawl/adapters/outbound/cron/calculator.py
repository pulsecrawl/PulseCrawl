"""Cron parsing adapter; scheduling receives an injected wall clock."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _croniter(expression: str, start: datetime):
    try:
        from croniter import croniter
    except ImportError as missing:  # pragma: no cover
        raise ImportError(
            "local schedules need croniter: pip install 'pulsecrawl[workspace]'"
        ) from missing
    return croniter(expression, start)


def validate_cron(expression: str, timezone_name: str = "UTC") -> tuple[str, ZoneInfo]:
    if len(expression) > 256 or len(timezone_name) > 128:
        raise ValueError("schedule or timezone is too long")
    normalized = " ".join(expression.split())
    if len(normalized.split()) != 5:
        raise ValueError("schedule must be an exact five-field cron expression")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown IANA timezone: {timezone_name}") from exc
    # Check a long occurrence window in real UTC time. This rejects every
    # sub-hour expression, including combinations whose textual fields look
    # harmless and timezone/DST edge cases.
    start = datetime(2026, 1, 1, tzinfo=zone)
    iterator = _croniter(normalized, start)
    previous = iterator.get_next(datetime)
    for _ in range(799):
        current = iterator.get_next(datetime)
        if (
            current.astimezone(timezone.utc) - previous.astimezone(timezone.utc)
        ).total_seconds() < 3600:
            raise ValueError("schedule cadence must be at least one hour")
        previous = current
    return normalized, zone


def _next(expression: str, zone: ZoneInfo, after: datetime | None = None) -> str:
    base = (after or datetime.now(timezone.utc)).astimezone(zone)
    value = _croniter(expression, base).get_next(datetime)
    return value.astimezone(timezone.utc).isoformat()


class CronScheduleCalculator:
    def validate(self, expression, timezone_name):
        return validate_cron(expression, timezone_name)

    def next(self, expression, zone, after):
        return _next(expression, zone, after)
