"""Privacy-safe health information shared by cloud and direct collection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class TelemetryHealth:
    """Track successful polls separately from changes in reported values."""

    def __init__(self) -> None:
        self.last_successful_poll: datetime | None = None
        self.last_value_change: datetime | None = None
        self.successful_polls = 0
        self.repeated_snapshots = 0
        self._previous_values: dict[str, Any] | None = None

    def observe(self, values: dict[str, Any]) -> datetime:
        """Record a successful collection without treating repeats as fresh data."""
        now = datetime.now(timezone.utc)
        self.last_successful_poll = now
        self.successful_polls += 1
        if self._previous_values != values:
            self.last_value_change = now
            self._previous_values = values.copy()
            self.repeated_snapshots = 0
        else:
            self.repeated_snapshots += 1
        return self.last_value_change


def diagnostic_summary(
    source: str,
    interval_seconds: int,
    update_success: bool,
    health: TelemetryHealth,
    field_count: int,
    source_available: bool | None,
) -> dict[str, Any]:
    """Allowlist operational fields so diagnostics cannot export raw telemetry."""
    return {
        "source": source,
        "configured_interval_seconds": interval_seconds,
        "last_update_success": update_success,
        "successful_polls_since_setup": health.successful_polls,
        "consecutive_repeated_snapshots": health.repeated_snapshots,
        "last_successful_poll": (
            health.last_successful_poll.isoformat()
            if health.last_successful_poll else None
        ),
        "last_value_change": (
            health.last_value_change.isoformat()
            if health.last_value_change else None
        ),
        "field_count": field_count,
        "source_reported_available": source_available,
        "note": "A repeated cloud response does not prove the inverter is offline.",
    }
