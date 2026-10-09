from __future__ import annotations

from datetime import timedelta
import logging

from aiohttp import ClientError, ClientResponseError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_SCAN_INTERVAL, CONF_URL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SolarMaxCoordinator(DataUpdateCoordinator[dict]):
    """Poll the analyzer's cached state without opening another Modbus session."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.base_url = str(entry.data[CONF_URL]).rstrip("/")
        interval = int(entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=max(10, interval)),
        )

    async def _async_update_data(self) -> dict:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(f"{self.base_url}/api/ha", timeout=10) as response:
                response.raise_for_status()
                return await response.json()
        except (ClientError, ClientResponseError, TimeoutError, ValueError) as exc:
            raise UpdateFailed(f"SolarMax analyzer unavailable: {exc}") from exc
