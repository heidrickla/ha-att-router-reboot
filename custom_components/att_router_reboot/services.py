"""The reboot action, registered at component setup."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN, SERVICE_REBOOT
from .coordinator import AttRouterConfigEntry

# The integration allows one entry, so the action takes no target.
REBOOT_SCHEMA = vol.Schema({})


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the reboot action once, independent of any entry."""

    def _entry() -> AttRouterConfigEntry:
        entries: list[AttRouterConfigEntry] = hass.config_entries.async_loaded_entries(
            DOMAIN
        )
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_loaded"
            )
        return entries[0]

    async def _reboot(call: ServiceCall) -> None:
        await _entry().runtime_data.async_reboot()

    hass.services.async_register(DOMAIN, SERVICE_REBOOT, _reboot, schema=REBOOT_SCHEMA)
