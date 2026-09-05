"""The built-in schedule: it fires, respects the day, and guards against loops."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.att_router_reboot.const import (
    CONF_SCHEDULE,
    CONF_SCHEDULE_TIME,
    CONF_SCHEDULE_WEEKDAY,
    DOMAIN,
    ISSUE_SCHEDULED_REBOOT_FAILED,
    SCHEDULE_DAILY,
    SCHEDULE_WEEKLY,
    WEEKDAYS,
)
from custom_components.att_router_reboot.models import GatewayData

from .conftest import REBOOT


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


async def _setup(hass, entry, gateway, options, uptime):
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options=options)
    gateway.uptime.return_value = uptime
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _fire_at(hass, when: datetime) -> None:
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    # Drive the registered time-change callbacks rather than sleeping a day;
    # this advances the clock the listeners watch.
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


async def test_a_daily_schedule_reboots_when_up_long_enough(
    hass, config_entry, gateway
):
    await _setup(
        hass,
        config_entry,
        gateway,
        {CONF_SCHEDULE: SCHEDULE_DAILY, CONF_SCHEDULE_TIME: "04:00:00"},
        uptime=7200,
    )
    with patch(REBOOT, AsyncMock()) as reboot:
        await _fire_at(hass, _next_local(4, 0))
    reboot.assert_awaited_once()


async def test_a_scheduled_reboot_is_skipped_on_a_just_booted_gateway(
    hass, config_entry, gateway
):
    """The loop guard: a schedule firing right after a reboot must not
    power-cycle the house's only internet again."""
    await _setup(
        hass,
        config_entry,
        gateway,
        {CONF_SCHEDULE: SCHEDULE_DAILY, CONF_SCHEDULE_TIME: "04:00:00"},
        uptime=60,
    )
    with patch(REBOOT, AsyncMock()) as reboot:
        await _fire_at(hass, _next_local(4, 0))
    reboot.assert_not_awaited()


async def test_a_weekly_schedule_fires_on_its_day(hass, config_entry, gateway):
    fire = _next_local(4, 0)
    await _setup(
        hass,
        config_entry,
        gateway,
        {
            CONF_SCHEDULE: SCHEDULE_WEEKLY,
            CONF_SCHEDULE_TIME: "04:00:00",
            CONF_SCHEDULE_WEEKDAY: WEEKDAYS[fire.weekday()],
        },
        uptime=7200,
    )
    with patch(REBOOT, AsyncMock()) as reboot:
        await _fire_at(hass, fire)
    reboot.assert_awaited_once()


async def test_a_weekly_schedule_ignores_the_wrong_day(hass, config_entry, gateway):
    fire = _next_local(4, 0)
    wrong = WEEKDAYS[(fire.weekday() + 1) % 7]
    await _setup(
        hass,
        config_entry,
        gateway,
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


def _issue(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_SCHEDULED_REBOOT_FAILED)


async def test_a_failing_scheduled_reboot_raises_a_repair_issue(
    hass, config_entry, gateway, caplog
):
    """A timer has no caller to report to. The failure must not escape, and it
    must not be a log line only: nobody reads the log for a 4 a.m. timer."""
    from custom_components.att_router_reboot.api import AttRouterError

    await _setup(
        hass,
        config_entry,
        gateway,
        {CONF_SCHEDULE: SCHEDULE_DAILY, CONF_SCHEDULE_TIME: "04:00:00"},
        uptime=7200,
    )
    with patch(REBOOT, AsyncMock(side_effect=AttRouterError("no form"))):
        await _fire_at(hass, _next_local(4, 0))
    assert "Scheduled reboot failed" in caplog.text
    issue = _issue(hass)
    assert issue is not None
    assert issue.translation_key == ISSUE_SCHEDULED_REBOOT_FAILED
    assert issue.translation_placeholders == {"error": "no form"}
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False


async def test_a_later_successful_scheduled_reboot_clears_the_issue(
    hass, config_entry, gateway
):
    from custom_components.att_router_reboot.api import AttRouterError

    fire = _next_local(4, 0)
    await _setup(
        hass,
        config_entry,
        gateway,
        {CONF_SCHEDULE: SCHEDULE_DAILY, CONF_SCHEDULE_TIME: "04:00:00"},
        uptime=7200,
    )
    with patch(REBOOT, AsyncMock(side_effect=AttRouterError("no form"))):
        await _fire_at(hass, fire)
    assert _issue(hass) is not None

    with patch(REBOOT, AsyncMock()):
        await _fire_at(hass, fire + timedelta(days=1))
    assert _issue(hass) is None


async def test_a_rejected_code_raises_reauth_and_not_a_repair_issue(
    hass, config_entry, gateway
):
    """Reauth is the better prompt for a changed code; two notices for one
    fault would just be noise."""
    from custom_components.att_router_reboot.api import AttRouterAuthError

    await _setup(
        hass,
        config_entry,
        gateway,
        {CONF_SCHEDULE: SCHEDULE_DAILY, CONF_SCHEDULE_TIME: "04:00:00"},
        uptime=7200,
    )
    with patch(REBOOT, AsyncMock(side_effect=AttRouterAuthError("rejected"))):
        await _fire_at(hass, _next_local(4, 0))
    assert _issue(hass) is None


async def test_a_rejected_code_on_a_scheduled_reboot_starts_reauth(
    hass, config_entry, gateway
):
    from homeassistant.config_entries import SOURCE_REAUTH

    from custom_components.att_router_reboot.api import AttRouterAuthError

    await _setup(
        hass,
        config_entry,
        gateway,
        {CONF_SCHEDULE: SCHEDULE_DAILY, CONF_SCHEDULE_TIME: "04:00:00"},
        uptime=7200,
    )
    with patch(REBOOT, AsyncMock(side_effect=AttRouterAuthError("rejected"))):
        await _fire_at(hass, _next_local(4, 0))
    assert any(
        flow["context"].get("source") == SOURCE_REAUTH
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_no_timer_is_registered_when_the_schedule_is_off(
    hass, config_entry, gateway
):
    await _setup(hass, config_entry, gateway, {}, uptime=7200)
    with patch(REBOOT, AsyncMock()) as reboot:
        await _fire_at(hass, _next_local(4, 0))
    reboot.assert_not_awaited()


def test_gateway_data_default_broadband_is_empty():
    data = GatewayData(uptime=5)
    assert data.broadband.connection_up is None
