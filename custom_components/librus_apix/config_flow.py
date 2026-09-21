"""Config flow for Librus APIX integration."""

import logging
from collections.abc import Mapping

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.core import callback
from homeassistant.helpers import selector

from librus_apix.client import new_client

from .const import (
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict):
    """Validate the user input allows us to connect."""
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    
    # Test authentication
    try:
        client = await hass.async_add_executor_job(new_client)
        token = await hass.async_add_executor_job(client.get_token, username, password)
        
        if not token:
            raise ValueError("Authentication failed")
            
        return {"title": f"Librus APIX ({username})"}
    
    except Exception as ex:
        _LOGGER.error("Authentication error: %s", ex)
        raise ValueError("Cannot connect") from ex


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Librus APIX."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "OptionsFlowHandler":
        """Zwroc obsluge opcji integracji."""
        return OptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors = {}
        
        if user_input is not None:
            self._async_abort_entries_match(
                {CONF_USERNAME: user_input[CONF_USERNAME]}
            )
            try:
                info = await validate_input(self.hass, user_input)
            except ValueError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, object]
    ) -> ConfigFlowResult:
        """Rozpocznij ponowna autoryzacje wpisu."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Popros o nowe haslo i przeladuj wpis po poprawnym logowaniu."""
        errors = {}
        reauth_entry = self._get_reauth_entry()
        username = reauth_entry.data[CONF_USERNAME]

        if user_input is not None:
            new_data = {
                CONF_USERNAME: username,
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                await validate_input(self.hass, new_data)
            except ValueError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry, data=new_data
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"username": username},
        )


class OptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Opcje integracji - na razie tylko czestotliwosc odpytywania Librusa.

    OptionsFlowWithReload sam przeladowuje wpis po zapisaniu opcji, wiec nowy
    interwal zaczyna obowiazywac od razu, bez restartu Home Assistanta.
    """

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Formularz opcji."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        biezacy = self.config_entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
        )
        schemat = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL_MINUTES, default=biezacy
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL_MINUTES,
                        max=MAX_SCAN_INTERVAL_MINUTES,
                        step=5,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schemat)
