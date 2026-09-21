"""Config flow for Librus APIX integration."""

import logging
from collections.abc import Mapping

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from librus_apix.client import new_client
from librus_apix.exceptions import AuthorizationError, MaintananceError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class CannotConnect(Exception):
    """Error to indicate we cannot connect to Librus."""


class InvalidAuth(Exception):
    """Error to indicate Librus rejected the credentials."""


async def validate_input(
    hass: HomeAssistant, data: dict[str, str]
) -> dict[str, str]:
    """Validate that the supplied credentials work."""
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]

    try:
        client = await hass.async_add_executor_job(new_client)
        token = await hass.async_add_executor_job(
            client.get_token, username, password
        )
    except AuthorizationError as err:
        raise InvalidAuth from err
    except MaintananceError as err:
        raise CannotConnect from err
    except OSError as err:
        raise CannotConnect from err

    if not token:
        raise InvalidAuth

    return {"title": f"Librus APIX ({username})"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Librus APIX."""

    VERSION = 1

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
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
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
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during reauthentication")
                errors["base"] = "unknown"
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

