"""The built-in schedule: it fires, respects the day, and guards against loops."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.util import dt as dt_util

from custom_components.att_router_reboot.const import (
    CONF_SCHEDULE,
    CONF_SCHEDULE_TIME,
    CONF_SCHEDULE_WEEKDAY,
    SCHEDULE_DAILY,
    SCHEDULE_WEEKLY,
    WEEKDAYS,
)
from custom_components.att_router_reboot.models import BroadbandStats, GatewayData

UPTIME = "custom_components.att_router_reboot.api.AttRouterClient.async_get_uptime"
MODEL = "custom_components.att_router_reboot.api.AttRouterClient.async_get_model"
BROADBAND = (
    "custom_components.att_router_reboot.api.AttRouterClient.async_get_broadband"
)
REBOOT = "custom_components.att_router_reboot.api.AttRouterClient.async_reboot"


def _next_local(hour: int, minute: int) -> datetime:
    """The next wall-clock occurrence of hour:minute, in local time.

    Firing at a time already past today would not trigger a listener scheduled
    for the next occurrence, so tests fire at the real next one.
    """
    now = dt_util.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


async def _setup(hass, entry, options, uptime):
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options=options)
    with (
        patch(UPTIME, return_value=uptime),
        patch(MODEL, return_value={}),
        patch(BROADBAND, return_value=BroadbandStats(connection_up=True)),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def _fire_at(hass, when: datetime) -> None:
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    # Drive the registered time-change callbacks rather than sleeping a day;
    # this advances the clock the listeners watch.
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


async def test_a_daily_schedule_reboots_when_up_long_enough(hass, config_entry):
    await _setup(
        hass,
        config_entry,
        {CONF_SCHEDULE: SCHEDULE_DAILY, CONF_SCHEDULE_TIME: "04:00:00"},
        uptime=7200,
    )
    with patch(REBOOT, AsyncMock()) as reboot, patch(UPTIME, return_value=1):
        await _fire_at(hass, _next_local(4, 0))
    reboot.assert_awaited_once()


async def test_a_scheduled_reboot_is_skipped_on_a_just_booted_gateway(
    hass, config_entry
):
    """The loop guard: a schedule firing right after a reboot must not
    power-cycle the house's only internet again."""
    await _setup(
        hass,
        config_entry,
        {CONF_SCHEDULE: SCHEDULE_DAILY, CONF_SCHEDULE_TIME: "04:00:00"},
        uptime=60,
    )
    with patch(REBOOT, AsyncMock()) as reboot:
        await _fire_at(hass, _next_local(4, 0))
    reboot.assert_not_awaited()


async def test_a_weekly_schedule_fires_on_its_day(hass, config_entry):
    fire = _next_local(4, 0)
    await _setup(
        hass,
        config_entry,
        {
            CONF_SCHEDULE: SCHEDULE_WEEKLY,
            CONF_SCHEDULE_TIME: "04:00:00",
            CONF_SCHEDULE_WEEKDAY: WEEKDAYS[fire.weekday()],
        },
        uptime=7200,
    )
    with patch(REBOOT, AsyncMock()) as reboot, patch(UPTIME, return_value=1):
        await _fire_at(hass, fire)
    reboot.assert_awaited_once()


async def test_a_weekly_schedule_ignores_the_wrong_day(hass, config_entry):
    fire = _next_local(4, 0)
    wrong = WEEKDAYS[(fire.weekday() + 1) % 7]
    await _setup(
        hass,
        config_entry,
        {
            CONF_SCHEDULE: SCHEDULE_WEEKLY,
            CONF_SCHEDULE_TIME: "04:00:00",
            CONF_SCHEDULE_WEEKDAY: wrong,
        },
        uptime=7200,
    )
    with patch(REBOOT, AsyncMock()) as reboot:
        await _fire_at(hass, fire)
    reboot.assert_not_awaited()


async def test_a_failing_scheduled_reboot_is_logged_not_raised(
    hass, config_entry, caplog
):
    """A timer has no caller to report to; the failure must not escape."""
    from custom_components.att_router_reboot.api import AttRouterError

    await _setup(
        hass,
        config_entry,
        {CONF_SCHEDULE: SCHEDULE_DAILY, CONF_SCHEDULE_TIME: "04:00:00"},
        uptime=7200,
    )
    with patch(REBOOT, AsyncMock(side_effect=AttRouterError("no form"))):
        await _fire_at(hass, _next_local(4, 0))
    assert "Scheduled reboot failed" in caplog.text


async def test_a_rejected_code_on_a_scheduled_reboot_starts_reauth(hass, config_entry):
    from homeassistant.config_entries import SOURCE_REAUTH

    from custom_components.att_router_reboot.api import AttRouterAuthError

    await _setup(
        hass,
        config_entry,
        {CONF_SCHEDULE: SCHEDULE_DAILY, CONF_SCHEDULE_TIME: "04:00:00"},
        uptime=7200,
    )
    with patch(REBOOT, AsyncMock(side_effect=AttRouterAuthError("rejected"))):
        await _fire_at(hass, _next_local(4, 0))
    assert any(
        flow["context"].get("source") == SOURCE_REAUTH
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_no_timer_is_registered_when_the_schedule_is_off(hass, config_entry):
    await _setup(hass, config_entry, {}, uptime=7200)
    with patch(REBOOT, AsyncMock()) as reboot:
        await _fire_at(hass, _next_local(4, 0))
    reboot.assert_not_awaited()


def test_gateway_data_default_broadband_is_empty():
    data = GatewayData(uptime=5)
    assert data.broadband.connection_up is None
