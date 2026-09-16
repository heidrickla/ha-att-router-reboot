"""Sensors: uptime, plus the broadband (WAN) statistics.

All of these come from pages the gateway serves without a login, so they cost
nothing beyond the poll that already runs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AttRouterConfigEntry, AttRouterCoordinator
from .entity import AttRouterEntity
from .models import GatewayData

# Read from values already in the coordinator; nothing to serialise.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AttRouterSensorDescription(SensorEntityDescription):
    """A sensor plus how to pull its value out of one poll."""

    value_fn: Callable[[GatewayData], int | str | None]


SENSORS: tuple[AttRouterSensorDescription, ...] = (
    AttRouterSensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda d: d.uptime,
    ),
    AttRouterSensorDescription(
        key="wan_ip",
        translation_key="wan_ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.broadband.ipv4_address,
    ),
    AttRouterSensorDescription(
        key="line_rate",
        translation_key="line_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.broadband.speed_mbps,
    ),
    # Counters. TOTAL_INCREASING, not TOTAL: they reset to zero when the
    # gateway reboots, which is exactly the reset semantics that class handles.
    AttRouterSensorDescription(
        key="rx_bytes",
        translation_key="rx_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=lambda d: d.broadband.rx_bytes,
    ),
    AttRouterSensorDescription(
        key="tx_bytes",
        translation_key="tx_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=lambda d: d.broadband.tx_bytes,
    ),
    AttRouterSensorDescription(
        key="rx_errors",
        translation_key="rx_errors",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.broadband.rx_errors,
    ),
    AttRouterSensorDescription(
        key="tx_errors",
        translation_key="tx_errors",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.broadband.tx_errors,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AttRouterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        AttRouterSensor(coordinator, description) for description in SENSORS
    )


class AttRouterSensor(AttRouterEntity, SensorEntity):
    """One value read from a gateway page."""

    entity_description: AttRouterSensorDescription

    def __init__(
        self,
        coordinator: AttRouterCoordinator,
        description: AttRouterSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    @override
    def native_value(self) -> int | str | None:
        return self.entity_description.value_fn(self.coordinator.data)
