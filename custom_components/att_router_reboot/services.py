"""The reboot action, registered at component setup."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import AttRouterAuthError, AttRouterError
from .const import DOMAIN, SERVICE_REBOOT
from .coordinator import AttRouterConfigEntry

REBOOT_SCHEMA = vol.Schema({vol.Optional("entry_id"): cv.string})


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
        coordinator = _entry().runtime_data
        try:
            await coordinator.client.async_reboot()
        except AttRouterAuthError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except AttRouterError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="reboot_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REBOOT, _reboot, schema=REBOOT_SCHEMA)
