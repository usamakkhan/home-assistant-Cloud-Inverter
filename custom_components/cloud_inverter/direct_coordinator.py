"""Read a SolarMax PV9000 inverter directly from Home Assistant."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_HOST, CONF_PORT, CONF_UNIT_ID, CONF_SCAN_INTERVAL,
    DEFAULT_DIRECT_UNIT_ID, DEFAULT_LOCAL_SCAN_INTERVAL, DOMAIN,
)
from .direct_profile.ha import seconds_until_safe_window, snapshot_payload
from .direct_profile.profile import read_profile_snapshot

_LOGGER = logging.getLogger(__name__)


class DirectSolarMaxCoordinator(DataUpdateCoordinator[dict]):
    """Own one serialized, read-only Modbus capture for a config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.host = str(entry.options.get(CONF_HOST, entry.data[CONF_HOST]))
        self.port = int(entry.options.get(CONF_PORT, entry.data[CONF_PORT]))
        self.unit_id = int(entry.options.get(
            CONF_UNIT_ID, entry.data.get(CONF_UNIT_ID, DEFAULT_DIRECT_UNIT_ID)
        ))
        interval = int(entry.options.get(
            CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_LOCAL_SCAN_INTERVAL)
        ))
        self._metadata_cache: dict = {}
        self._capture_lock = asyncio.Lock()
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_direct",
            update_interval=timedelta(seconds=max(10, interval)),
        )

    async def _async_update_data(self) -> dict:
        async with self._capture_lock:
            delay = seconds_until_safe_window(time.time())
            if delay:
                _LOGGER.debug("Delaying SolarMax capture %.0f seconds for cloud quiet window", delay)
                await asyncio.sleep(delay)
            try:
                snapshot = await self.hass.async_add_executor_job(
                    read_profile_snapshot,
                    self.host,
                    self.unit_id,
                    4,
                    1.0,
                    self._metadata_cache,
                    300.0,
                    self.port,
                )
                return snapshot_payload(snapshot)
            except (OSError, ValueError, RuntimeError) as exc:
                raise UpdateFailed(f"SolarMax direct read failed: {exc}") from exc
