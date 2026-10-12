"""Shared conservative timing policy for origin dispatch gates."""

from __future__ import annotations


DEFAULT_DISPATCH_MARGIN_RATIO = 0.10


def guarded_interval_s(
    interval_s: float,
    margin_ratio: float = DEFAULT_DISPATCH_MARGIN_RATIO,
) -> float:
    """Return an interval with a conservative dispatch-to-wire margin."""

    if interval_s < 0:
        raise ValueError("interval_s must be non-negative")
    if margin_ratio < 0:
        raise ValueError("margin_ratio must be non-negative")
    return interval_s * (1.0 + margin_ratio)
