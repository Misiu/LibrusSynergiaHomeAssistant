"""The Librus Synergia integration."""

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from librus_apix.exceptions import AuthorizationError

from .api import LibrusApiClient
from .const import DOMAIN
from .coordinator import LibrusConfigEntry, LibrusDataUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.CALENDAR]

async def async_setup_entry(hass: HomeAssistant, entry: LibrusConfigEntry) -> bool:
    """Set up Librus Synergia from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
 
    client = LibrusApiClient(username, password)
    
    if not await client.async_authenticate():
        if isinstance(client.last_auth_error, AuthorizationError):
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
            )
        raise ConfigEntryNotReady("Librus authentication is temporarily unavailable")
    
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LibrusConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)