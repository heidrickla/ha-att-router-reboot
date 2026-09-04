"""Polling coordinator: reads the gateway's uptime on a schedule."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AttRouterClient, AttRouterConnectionError, AttRouterError
from .const import DOMAIN, SCAN_INTERVAL
from .models import GatewayData

_LOGGER = logging.getLogger(__name__)

type AttRouterConfigEntry = ConfigEntry[AttRouterCoordinator]


class AttRouterCoordinator(DataUpdateCoordinator[GatewayData]):
    """Fetches uptime; owns the client and its HTTP session.

    The data payload is a GatewayData: uptime plus the broadband statistics,
    both read without a login. Reboot is a command, driven by the
    button/action/schedule, not by polling.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: AttRouterConfigEntry,
        client: AttRouterClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.model_info: dict[str, str] = {}

    async def _async_setup(self) -> None:
        """One-time model lookup, so device_info is populated from first load."""
        try:
            self.model_info = await self.client.async_get_model()
        except AttRouterError as err:
            # Not fatal: uptime is what the entities need. Model just enriches
            # the device page, so a miss here should not block setup.
            _LOGGER.debug("Could not read model info: %s", err)

    async def _async_update_data(self) -> GatewayData:
        try:
            uptime = await self.client.async_get_uptime()
        except AttRouterConnectionError as err:
            raise UpdateFailed(f"gateway unreachable: {err}") from err
        except AttRouterError as err:
            raise UpdateFailed(str(err)) from err

        # Broadband stats are a bonus, not a reason to fail the whole poll:
        # uptime is what the reboot logic and the schedule guard depend on.
        try:
            broadband = await self.client.async_get_broadband()
        except AttRouterError as err:
            _LOGGER.debug("Could not read broadband statistics: %s", err)
            broadband = (
                self.data.broadband if self.data else GatewayData(uptime).broadband
            )

        return GatewayData(uptime=uptime, broadband=broadband)
