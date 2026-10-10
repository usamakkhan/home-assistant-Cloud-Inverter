"""The Cloud Inverter integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .const import DOMAIN, CONF_GOODS_ID, CONF_SOURCE, SOURCE_CLOUD, SOURCE_DIRECT
from .direct_coordinator import DirectSolarMaxCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Cloud Inverter from a config entry."""
    # Keep user-customized titles; migrate only titles created by older releases.
    if entry.title == "Cloud Inverter Direct":
        hass.config_entries.async_update_entry(entry, title="Solar Touch Direct")
    elif entry.title.startswith("Cloud Inverter ("):
        hass.config_entries.async_update_entry(
            entry, title="Solar Touch (" + entry.title[len("Cloud Inverter ("):]
        )
    hass.data.setdefault(DOMAIN, {})
    
    # Keep only the selected inverter reference in integration state.
    source = entry.data.get(CONF_SOURCE, SOURCE_CLOUD)
    if source == SOURCE_DIRECT:
        coordinator = DirectSolarMaxCoordinator(hass, entry)
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
    elif source != SOURCE_CLOUD:
        raise ConfigEntryError(
            "This old local analyzer entry needs to be removed and re-added "
            "using Get Data Locally using Inverter IP"
        )
    hass.data[DOMAIN][entry.entry_id] = {"goods_id": entry.data.get(CONF_GOODS_ID)}
    
    _LOGGER.info("Setting up Cloud Inverter %s integration", source)
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        if entry.data.get(CONF_SOURCE, SOURCE_CLOUD) == SOURCE_CLOUD:
            api = getattr(getattr(entry, "runtime_data", None), "api", None)
            if api is not None:
                await api.close()
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.info("Unloaded Cloud Inverter integration")
    
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
