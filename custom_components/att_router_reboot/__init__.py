"""The AT&T Router Reboot integration."""

from __future__ import annotations

from aiohttp import CookieJar
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import AttRouterClient
from .const import CONF_ACCESS_CODE, CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL, DOMAIN
from .coordinator import AttRouterConfigEntry, AttRouterCoordinator
from .schedule import async_setup_schedule
from .services import async_setup_services

# Nothing is configured from YAML; async_setup exists only to register the
# action, and hassfest wants that said explicitly.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

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
    # A session of its own, not the shared one: the gateway's SessionID cookie
    # must not leak into other integrations' requests. The jar is the unsafe
    # one because the gateway is addressed by IP and aiohttp's default jar
    # drops cookies from IP hosts, which is the "enable cookies" stub in
    # api.py. The helper closes the session when the entry unloads.
    session = async_create_clientsession(
        hass,
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        cookie_jar=CookieJar(unsafe=True),
    )
    client = AttRouterClient(
        session, entry.data[CONF_HOST], entry.data[CONF_ACCESS_CODE]
    )

    coordinator = AttRouterCoordinator(hass, entry, client)
    # The first refresh raises a bare ConfigEntryNotReady with the coordinator's
    # UpdateFailed as its cause; the released core reads the reason from the
    # exception itself, not the cause, so the translation is lifted up here.
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady as err:
        cause = err.__cause__
        if isinstance(cause, UpdateFailed) and cause.translation_key:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key=cause.translation_key,
                translation_placeholders=cause.translation_placeholders,
            ) from cause
        raise

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_setup_schedule(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AttRouterConfigEntry) -> bool:
    """Unload a config entry. The reboot action stays registered - see async_setup."""
    unloaded: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: AttRouterConfigEntry) -> None:
    """Reload when options (the schedule) change."""
    await hass.config_entries.async_reload(entry.entry_id)
