"""Polling coordinator: reads the gateway's uptime on a schedule."""

from __future__ import annotations

import logging
from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AttRouterAuthError,
    AttRouterClient,
    AttRouterConnectionError,
    AttRouterError,
)
from .const import DOMAIN, ISSUE_SCHEDULED_REBOOT_FAILED, SCAN_INTERVAL
from .models import GatewayData, SysInfo

_LOGGER = logging.getLogger(__name__)

type AttRouterConfigEntry = ConfigEntry[AttRouterCoordinator]


class AttRouterCoordinator(DataUpdateCoordinator[GatewayData]):
    """Fetches uptime; owns the client.

    The data payload is a GatewayData: uptime plus the broadband statistics,
    both read without a login. Reboot is a command, driven by the
    button/action/schedule through async_reboot, not by polling.
    """

    config_entry: AttRouterConfigEntry

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
        self._broadband_available = True
        self._last_uptime: int | None = None

    @override
    async def _async_setup(self) -> None:
        """One-time model lookup, so device_info is populated from first load."""
        try:
            self.model_info = await self.client.async_get_model()
        except AttRouterError as err:
            # Not fatal: uptime is what the entities need. Model just enriches
            # the device page, so a miss here should not block setup.
            _LOGGER.debug("Could not read model info: %s", err)

    @override
    async def _async_update_data(self) -> GatewayData:
        try:
            sysinfo = await self.client.async_get_sysinfo()
        except AttRouterConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        except AttRouterError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        self._refresh_device_info(sysinfo)
        uptime = sysinfo.uptime
        firmware = sysinfo.info.get("firmware")

        # Broadband stats are a bonus, not a reason to fail the whole poll:
        # uptime is what the reboot logic and the schedule guard depend on.
        # Logged once when the page is lost and once when it is back.
        try:
            broadband = await self.client.async_get_broadband()
        except AttRouterError as err:
            if self._broadband_available:
                _LOGGER.info("Broadband statistics are unavailable: %s", err)
                self._broadband_available = False
            return GatewayData(uptime=uptime, firmware=firmware, broadband_read=False)
        if not self._broadband_available:
            _LOGGER.info("Broadband statistics are available again")
            self._broadband_available = True
        return GatewayData(uptime=uptime, firmware=firmware, broadband=broadband)

    def _refresh_device_info(self, sysinfo: SysInfo) -> None:
        """Keep the device page's firmware current after a gateway update.

        The device keeps the firmware it was given at setup, so a new version,
        or an uptime that went backwards (the gateway rebooted), writes the
        page's value to the stored identity and the device registry. The
        registry write changes nothing when the value is the same, and a page
        that omits the version never blanks the one on file.
        """
        rebooted = self._last_uptime is not None and sysinfo.uptime < self._last_uptime
        self._last_uptime = sysinfo.uptime
        firmware = sysinfo.info.get("firmware")
        if firmware is None:
            return
        if not rebooted and firmware == self.model_info.get("firmware"):
            return
        self.model_info = {**self.model_info, "firmware": firmware}
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(
            identifiers={(DOMAIN, self.config_entry.entry_id)}
        )
        if device is not None:
            registry.async_update_device(device.id, sw_version=firmware)

    async def async_reboot(self) -> None:
        """Reboot the gateway. The one path the button, action and schedule share.

        A rejected access code starts the reauth flow, so the user is asked
        for the new code instead of finding out from a failed automation.
        """
        try:
            await self.client.async_reboot()
        except AttRouterAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
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
        # A reboot by any path clears the scheduled-reboot issue, which tells
        # the user to press Reboot.
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_SCHEDULED_REBOOT_FAILED)
        await self.async_request_refresh()
