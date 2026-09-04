"""The reboot button."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import AttRouterAuthError, AttRouterError
from .const import DOMAIN
from .coordinator import AttRouterConfigEntry, AttRouterCoordinator
from .entity import AttRouterEntity

# The gateway serialises its own logins, and a reboot is not something to fire
# twice concurrently, so keep entity commands one at a time.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AttRouterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AttRouterRebootButton(entry.runtime_data)])


class AttRouterRebootButton(AttRouterEntity, ButtonEntity):
    """Reboots the gateway when pressed."""

    _attr_translation_key = "reboot"
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator: AttRouterCoordinator) -> None:
        super().__init__(coordinator, "reboot")

    async def async_press(self) -> None:
        try:
            await self.coordinator.client.async_reboot()
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
        await self.coordinator.async_request_refresh()
