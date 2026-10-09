"""The Cloud Inverter integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_GOODS_ID, CONF_SOURCE, SOURCE_CLOUD, SOURCE_LOCAL
from .local_coordinator import SolarMaxCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Cloud Inverter from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Keep only the selected inverter reference in integration state.
    source = entry.data.get(CONF_SOURCE, SOURCE_CLOUD)
    if source == SOURCE_LOCAL:
        coordinator = SolarMaxCoordinator(hass, entry)
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
    hass.data[DOMAIN][entry.entry_id] = {"goods_id": entry.data.get(CONF_GOODS_ID)}
    
    _LOGGER.info("Setting up Cloud Inverter %s integration", source)
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.info("Unloaded Cloud Inverter integration")
    
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
