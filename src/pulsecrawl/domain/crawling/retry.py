"""Bounded Retry-After policy with explicit current time."""

from datetime import timezone
from email.utils import parsedate_to_datetime
import math


def retry_after_seconds(value: str | None, retry_count: int, now) -> float:
    """Return a bounded retry delay for transient server responses."""
    fallback = min(2.0**retry_count, 30.0)
    if value is None:
        return fallback
    try:
        seconds = float(value.strip())
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = (when - now.astimezone(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return fallback
    if not math.isfinite(seconds):
        return fallback
    return min(max(seconds, 0.0), 300.0)
