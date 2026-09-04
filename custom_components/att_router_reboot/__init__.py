"""The AT&T Router Reboot integration."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType

from .api import (
    AttRouterAuthError,
    AttRouterClient,
    AttRouterConnectionError,
    AttRouterError,
)
from .const import CONF_ACCESS_CODE, CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL
from .coordinator import AttRouterConfigEntry, AttRouterCoordinator
from .schedule import async_setup_schedule
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the reboot action once, at component setup.

    Registered here rather than per entry so an automation calling it fails
    with a translated refusal while the entry is unloaded, instead of looking
    like a typo.
    """
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AttRouterConfigEntry) -> bool:
    """Set up from a config entry."""
    session = aiohttp.ClientSession()
    client = AttRouterClient(
        session,
        entry.data[CONF_HOST],
        entry.data[CONF_ACCESS_CODE],
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )

    async def _close_session() -> None:
        await session.close()

    # Registered before the first refresh so a gateway that is unreachable at
    # startup does not leak a session per retry.
    entry.async_on_unload(_close_session)

    coordinator = AttRouterCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    except AttRouterAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except AttRouterConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err
    except AttRouterError as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_setup_schedule(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AttRouterConfigEntry) -> bool:
    """Unload a config entry. The reboot action stays registered - see async_setup."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: AttRouterConfigEntry) -> None:
    """Reload when options (the schedule) change."""
    await hass.config_entries.async_reload(entry.entry_id)
