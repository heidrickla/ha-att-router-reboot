"""Binary sensors: whether the gateway answered, and whether the WAN is up."""

from __future__ import annotations

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AttRouterConfigEntry, AttRouterCoordinator
from .entity import AttRouterEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AttRouterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            AttRouterReachableSensor(coordinator),
            AttRouterWanConnectedSensor(coordinator),
        ]
    )


class AttRouterReachableSensor(AttRouterEntity, BinarySensorEntity):
    """On when the gateway's web interface answered the last uptime poll.

    Leans on the coordinator's own success flag rather than inventing a
    separate probe. The entity itself stays available so the fault is visible -
    blanking it would hide exactly what it exists to report.
    """

    _attr_translation_key = "reachable"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AttRouterCoordinator) -> None:
        super().__init__(coordinator, "reachable")

    @property
    @override
    def available(self) -> bool:
        return True

    @property
    @override
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class AttRouterWanConnectedSensor(AttRouterEntity, BinarySensorEntity):
    """On when the gateway reports its broadband (WAN) connection as up.

    Distinct from reachability: the gateway can answer perfectly while its
    upstream fibre/ethernet link is down.
    """

    _attr_translation_key = "wan_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: AttRouterCoordinator) -> None:
        super().__init__(coordinator, "wan_connected")

    @property
    @override
    def is_on(self) -> bool | None:
        return self.coordinator.data.broadband.connection_up
