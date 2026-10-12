"""Readiness timestamps are not elapsed-time measurements.

Durable adapters use epoch seconds so scheduled work survives process restarts.
Ephemeral adapters may use a process-relative coordinate. Legacy custom clocks
without readiness_time retain their original monotonic coordinate.
"""


def readiness_time(clock) -> float:
    read = getattr(clock, "readiness_time", None)
    return read() if read is not None else clock.monotonic()
