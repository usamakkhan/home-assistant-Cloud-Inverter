from __future__ import annotations

from typing import Any

from aiohttp import ClientError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_URL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_URL,
    DOMAIN,
)


class SolarMaxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the local analyzer endpoint."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = str(user_input[CONF_URL]).strip().rstrip("/")
            try:
                session = async_get_clientsession(self.hass)
                async with session.get(f"{base_url}/api/config", timeout=10) as response:
                    response.raise_for_status()
                    config = await response.json()
                if (
                    not str(config.get("version", "")).startswith("0.")
                    or config.get("read_only") is not True
                ):
                    errors["base"] = "invalid_response"
                else:
                    await self.async_set_unique_id(base_url.lower())
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"SolarMax Local Cloud ({base_url})",
                        data={
                            CONF_URL: base_url,
                            CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                        },
                    )
            except (ClientError, TimeoutError, ValueError):
                errors["base"] = "cannot_connect"

        schema = vol.Schema({
            vol.Required(CONF_URL, default=(user_input or {}).get(CONF_URL, DEFAULT_URL)): str,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=(user_input or {}).get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
