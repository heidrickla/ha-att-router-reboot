"""The optional built-in reboot schedule.

Home Assistant's idiomatic answer to "reboot every night" is an automation on
the button entity, and that stays available. But this integration exists for a
device whose owner may not write automations, so an off/daily/weekly schedule
lives in the options flow and is honoured here.

The guard matters: a scheduled reboot is skipped unless the gateway has been up
long enough, so the schedule cannot power-cycle the house's only internet
connection in a loop if it fires right after a manual reboot or a restart storm.
"""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_change

from .const import (
    CONF_SCHEDULE,
    CONF_SCHEDULE_TIME,
    CONF_SCHEDULE_WEEKDAY,
    DEFAULT_SCHEDULE,
    DEFAULT_SCHEDULE_TIME,
    DEFAULT_SCHEDULE_WEEKDAY,
    DOMAIN,
    ISSUE_SCHEDULED_REBOOT_FAILED,
    MIN_UPTIME_FOR_SCHEDULED_REBOOT,
    SCHEDULE_OFF,
    SCHEDULE_WEEKLY,
    WEEKDAYS,
)
from .coordinator import AttRouterConfigEntry

_LOGGER = logging.getLogger(__name__)


def _parse_time(value: str) -> tuple[int, int, int]:
    parts = [*value.split(":"), "0", "0", "0"][:3]
    return int(parts[0]), int(parts[1]), int(parts[2])


@callback
def async_setup_schedule(hass: HomeAssistant, entry: AttRouterConfigEntry) -> None:
    """Wire a time trigger if the options ask for one."""
    schedule = entry.options.get(CONF_SCHEDULE, DEFAULT_SCHEDULE)
    if schedule == SCHEDULE_OFF:
        return

    hour, minute, second = _parse_time(
        entry.options.get(CONF_SCHEDULE_TIME, DEFAULT_SCHEDULE_TIME)
    )
    weekday = entry.options.get(CONF_SCHEDULE_WEEKDAY, DEFAULT_SCHEDULE_WEEKDAY)
    coordinator = entry.runtime_data

    async def _fire(now: datetime) -> None:
        # async_track_time_change has no weekday filter, so a weekly schedule
        # fires daily and returns here on the wrong day.
        if schedule == SCHEDULE_WEEKLY and WEEKDAYS[now.weekday()] != weekday:
            return

        data = coordinator.data
        if (
            data is not None
            and data.uptime < MIN_UPTIME_FOR_SCHEDULED_REBOOT.total_seconds()
        ):
            _LOGGER.info(
                "Skipping scheduled reboot: gateway has only been up %d s",
                data.uptime,
            )
            return

        _LOGGER.info("Scheduled reboot firing")
        try:
            await coordinator.async_reboot()
        except HomeAssistantError as err:
            # Nobody is watching a timer fire. A rejected code has already
            # started the reauth flow, which is the better prompt; anything
            # else becomes a repair issue so it is more than a log line.
            _LOGGER.error("Scheduled reboot failed: %s", err)
            if err.translation_key != "auth_failed":
                detail = (err.translation_placeholders or {}).get("error") or str(err)
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    ISSUE_SCHEDULED_REBOOT_FAILED,
                    is_fixable=False,
                    issue_domain=DOMAIN,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_SCHEDULED_REBOOT_FAILED,
                    translation_placeholders={"error": detail},
                )
            return

        # A schedule that works again clears the warning it raised.
        ir.async_delete_issue(hass, DOMAIN, ISSUE_SCHEDULED_REBOOT_FAILED)

    entry.async_on_unload(
        async_track_time_change(hass, _fire, hour=hour, minute=minute, second=second)
    )
