"""Config flow for Cloud Inverter integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import CloudInverterAPI
from .direct_config import direct_unique_id, parse_direct_settings, probe_direct_inverter
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SOURCE,
    SOURCE_CLOUD,
    SOURCE_DIRECT,
    CONF_HOST,
    CONF_PORT,
    CONF_UNIT_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_DIRECT_PORT,
    DEFAULT_DIRECT_UNIT_ID,
    DEFAULT_DIRECT_SCAN_INTERVAL,
    MIN_CLOUD_SCAN_INTERVAL,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    api = CloudInverterAPI(
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar()),
        close_session=True,
    )
    
    try:
        if not await api.test_connection():
            raise InvalidAuth
        
        # Get the list of inverters
        groups = await api.get_group_list()
        if not groups:
            raise NoInvertersFound
            
        return {"groups": groups, "api": api}
    except NoInvertersFound:
        await api.close()
        raise
    except Exception:
        await api.close()
        raise


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cloud Inverter."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> config_entries.OptionsFlow:
        """Let users adjust the refresh interval after setup."""
        return CloudInverterOptionsFlow()

    def __init__(self):
        """Initialize the config flow."""
        self.username = None
        self.password = None
        self.api = None
        self.inverters = []
        self._direct_data: dict[str, Any] | None = None
        self._direct_probe_value: int | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose cloud access or direct LAN collection."""
        if user_input is not None:
            if user_input[CONF_SOURCE] == SOURCE_DIRECT:
                return await self.async_step_direct()
            return await self.async_step_cloud()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_SOURCE, default=SOURCE_DIRECT): vol.In({
                    SOURCE_DIRECT: "Get Data Locally using Inverter IP",
                    SOURCE_CLOUD: "CloudInverter.net",
                }),
            }),
        )

    async def async_step_direct(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure read-only Modbus collection inside Home Assistant."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._direct_data = None
            self._direct_probe_value = None
            try:
                host, port, unit_id = parse_direct_settings(
                    user_input[CONF_HOST], user_input[CONF_PORT], user_input[CONF_UNIT_ID]
                )
            except ValueError:
                errors["base"] = "invalid_direct_host"
            else:
                try:
                    probe_value = await self.hass.async_add_executor_job(
                        probe_direct_inverter, host, port, unit_id
                    )
                except (OSError, ConnectionError, TimeoutError):
                    errors["base"] = "cannot_read_direct"
                else:
                    await self.async_set_unique_id(direct_unique_id(host, port, unit_id))
                    self._abort_if_unique_id_configured()
                    self._direct_data = {
                        CONF_SOURCE: SOURCE_DIRECT,
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_UNIT_ID: unit_id,
                        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    }
                    self._direct_probe_value = probe_value
                    return await self.async_step_direct_confirm()
        return self.async_show_form(
            step_id="direct",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "192.168.50.10")): str,
                vol.Required(CONF_PORT, default=(user_input or {}).get(CONF_PORT, DEFAULT_DIRECT_PORT)):
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Required(CONF_UNIT_ID, default=(user_input or {}).get(CONF_UNIT_ID, DEFAULT_DIRECT_UNIT_ID)):
                    vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=(user_input or {}).get(CONF_SCAN_INTERVAL, DEFAULT_DIRECT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=900)),
            }),
            errors=errors,
        )

    async def async_step_direct_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create the entry only after the user sees a successful Modbus check."""
        if self._direct_data is None:
            return await self.async_step_direct()
        if user_input is not None:
            return self.async_create_entry(
                title="Solar Touch Direct",
                data=self._direct_data,
            )
        return self.async_show_form(
            step_id="direct_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "host": self._direct_data[CONF_HOST],
                "port": str(self._direct_data[CONF_PORT]),
                "unit_id": str(self._direct_data[CONF_UNIT_ID]),
                "register_value": str(self._direct_probe_value),
            },
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - username and password."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                
                # Store credentials and API
                self.username = user_input[CONF_USERNAME]
                self.password = user_input[CONF_PASSWORD]
                self.api = info["api"]
                
                # Get group details to show inverter options
                groups = info["groups"]
                inverter_options = {}
                
                for group in groups:
                    group_auto_id = str(group.get("AutoID"))
                    # Get detailed info for this group
                    detail = await self.api.get_group_detail(group_auto_id)
                    
                    if detail and "AllInverterList" in detail:
                        for inverter in detail["AllInverterList"]:
                            goods_id = inverter.get("GoodsID")
                            model_name = inverter.get("ModelName", "Unknown")
                            goods_name = inverter.get("GoodsName", goods_id)
                            
                            # Create a user-friendly display name
                            display_name = f"{model_name} - {goods_id}"
                            inverter_options[goods_id] = display_name
                            self.inverters.append({
                                "goods_id": goods_id,
                                "model": model_name,
                                "name": goods_name
                            })
                
                if not inverter_options:
                    raise NoInvertersFound
                
                # If only one inverter, skip selection and configure directly
                if len(inverter_options) == 1:
                    selected_goods_id = list(inverter_options.keys())[0]
                    return await self._create_entry(selected_goods_id)
                
                # Multiple inverters - show selection
                return await self.async_step_select_inverter(inverter_options)
                
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except NoInvertersFound:
                errors["base"] = "no_inverters"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            finally:
                # Clean up API if there was an error
                if errors and self.api:
                    await self.api.close()
                    self.api = None

        return self.async_show_form(
            step_id="cloud",
            data_schema=STEP_USER_DATA_SCHEMA, 
            errors=errors,
            description_placeholders={
                "note": "Enter your CloudInverter.net login credentials"
            }
        )

    async def async_step_select_inverter(
        self, inverter_options: dict[str, str] = None, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle inverter selection step."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            selected_goods_id = user_input["inverter"]
            return await self._create_entry(selected_goods_id)
        
        # Build the options dict if not provided
        if inverter_options is None:
            inverter_options = {}
            for inv in self.inverters:
                goods_id = inv["goods_id"]
                display_name = f"{inv['model']} - {goods_id}"
                inverter_options[goods_id] = display_name
        
        data_schema = vol.Schema(
            {
                vol.Required("inverter"): vol.In(inverter_options),
            }
        )
        
        return self.async_show_form(
            step_id="select_inverter",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "note": "Select your inverter. The ID shown matches the serial number on your inverter device."
            }
        )

    async def _create_entry(self, goods_id: str) -> FlowResult:
        """Create the config entry."""
        # Find the selected inverter info
        selected_inverter = None
        for inv in self.inverters:
            if inv["goods_id"] == goods_id:
                selected_inverter = inv
                break
        
        if not selected_inverter:
            selected_inverter = {"model": "Unknown", "name": goods_id}
        
        # Check if already configured
        await self.async_set_unique_id(f"{self.username}_{goods_id}")
        self._abort_if_unique_id_configured()
        
        # Clean up API
        if self.api:
            await self.api.close()
        
        title = f"Solar Touch ({selected_inverter['model']})"
        
        return self.async_create_entry(
            title=title,
            data={
                CONF_SOURCE: SOURCE_CLOUD,
                CONF_USERNAME: self.username,
                CONF_PASSWORD: self.password,
                "goods_id": goods_id,
                "model": selected_inverter["model"],
            }
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class NoInvertersFound(HomeAssistantError):
    """Error to indicate no inverters were found."""


class CloudInverterOptionsFlow(config_entries.OptionsFlowWithReload):
    """Options for the Home Assistant refresh interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the interval field and reload the entry after a change."""
        direct = self.config_entry.data.get(CONF_SOURCE) == SOURCE_DIRECT
        errors: dict[str, str] = {}
        if user_input is not None:
            options = {CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            if direct:
                try:
                    host, port, unit_id = parse_direct_settings(
                        user_input[CONF_HOST], user_input[CONF_PORT], user_input[CONF_UNIT_ID]
                    )
                except ValueError:
                    errors["base"] = "invalid_direct_host"
                else:
                    try:
                        await self.hass.async_add_executor_job(
                            probe_direct_inverter, host, port, unit_id
                        )
                    except (OSError, ConnectionError, TimeoutError):
                        errors["base"] = "cannot_read_direct"
                    else:
                        options.update({CONF_HOST: host, CONF_PORT: port, CONF_UNIT_ID: unit_id})
            if not errors:
                return self.async_create_entry(data=options)

        default = DEFAULT_DIRECT_SCAN_INTERVAL if direct else UPDATE_INTERVAL
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, default),
        )
        fields = {}
        if direct:
            fields[vol.Required(CONF_HOST, default=(user_input or {}).get(
                CONF_HOST, self.config_entry.options.get(CONF_HOST, self.config_entry.data[CONF_HOST])
            ))] = str
            fields[vol.Required(CONF_PORT, default=(user_input or {}).get(
                CONF_PORT, self.config_entry.options.get(CONF_PORT, self.config_entry.data[CONF_PORT])
            ))] = vol.All(vol.Coerce(int), vol.Range(min=1, max=65535))
            fields[vol.Required(CONF_UNIT_ID, default=(user_input or {}).get(
                CONF_UNIT_ID, self.config_entry.options.get(
                    CONF_UNIT_ID, self.config_entry.data.get(CONF_UNIT_ID, DEFAULT_DIRECT_UNIT_ID)
                )
            ))] = vol.All(vol.Coerce(int), vol.Range(min=0, max=255))
        fields[vol.Required(CONF_SCAN_INTERVAL, default=(user_input or {}).get(CONF_SCAN_INTERVAL, current))] = vol.All(
            vol.Coerce(int), vol.Range(min=10 if direct else MIN_CLOUD_SCAN_INTERVAL, max=900)
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(fields),
            errors=errors,
        )
