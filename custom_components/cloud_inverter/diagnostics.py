"""Redacted diagnostics for Solar Touch cloud and direct entries."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SOURCE,
    DEFAULT_DIRECT_SCAN_INTERVAL,
    SOURCE_CLOUD,
    SOURCE_DIRECT,
    UPDATE_INTERVAL,
)
from .health import diagnostic_summary


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Describe collection health without exporting credentials or telemetry."""
    source = entry.data.get(CONF_SOURCE, SOURCE_CLOUD)
    coordinator = entry.runtime_data
    payload = coordinator.data or {}
    health = coordinator.health
    default_interval = (
        DEFAULT_DIRECT_SCAN_INTERVAL if source == SOURCE_DIRECT else UPDATE_INTERVAL
    )
    sensors = payload.get("sensors", {}) if source == SOURCE_DIRECT else payload
    return diagnostic_summary(
        source=source,
        interval_seconds=int(entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, default_interval),
        )),
        update_success=coordinator.last_update_success,
        health=health,
        field_count=len(sensors) - ("_last_value_change" in sensors),
        source_available=payload.get("available") if source == SOURCE_DIRECT else None,
    )
