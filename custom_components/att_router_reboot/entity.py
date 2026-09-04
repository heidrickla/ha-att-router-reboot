"""Shared entity base bound to the one gateway."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import AttRouterCoordinator


class AttRouterEntity(CoordinatorEntity[AttRouterCoordinator]):
    """Base entity for the gateway."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AttRouterCoordinator, key: str) -> None:
        super().__init__(coordinator)
        # Always set: __init__.py passes config_entry to the coordinator.
        assert coordinator.config_entry is not None
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        info = coordinator.model_info
        mac = info.get("mac")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            manufacturer=MANUFACTURER,
            name="AT&T Gateway",
            model=info.get("model"),
            sw_version=info.get("firmware"),
            serial_number=info.get("serial"),
            # Ties the gateway to the same device the network already reports,
            # so it does not appear twice.
            connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
        )
