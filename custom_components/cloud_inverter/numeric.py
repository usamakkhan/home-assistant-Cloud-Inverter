"""Convert portal measurements to valid Home Assistant numeric states."""

from __future__ import annotations

from math import isfinite


def numeric_state(value: object) -> float | None:
    """Return a finite number, or no state for a missing/invalid reading."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value.replace(",", "") if isinstance(value, str) else value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None
