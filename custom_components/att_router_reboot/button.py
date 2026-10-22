"""The reboot button."""

from __future__ import annotations

from typing import override

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

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

    @override
    async def async_press(self) -> None:
        await self._async_require_admin()
        # Raises a translated HomeAssistantError and starts reauth on a
        # rejected code; see the coordinator.
        await self.coordinator.async_reboot()

    async def _async_require_admin(self) -> None:
        """Refuse a press by a signed-in user who is not an administrator."""
        context = self._context
        if context is None or context.user_id is None:
            return
        user = await self.hass.auth.async_get_user(context.user_id)
        if user is None or not user.is_admin:
            raise Unauthorized(context=context)
