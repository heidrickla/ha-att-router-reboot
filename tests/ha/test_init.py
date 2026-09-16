"""Setup, entities, the reboot action, reauth on a rejected code, diagnostics."""

from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import CookieJar
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_HOST, STATE_UNAVAILABLE
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from yarl import URL

from custom_components.att_router_reboot.api import (
    AttRouterAuthError,
    AttRouterConnectionError,
    AttRouterError,
)
from custom_components.att_router_reboot.const import (
    CONF_SCHEDULE,
    DOMAIN,
    SCHEDULE_DAILY,
    SERVICE_REBOOT,
)
from custom_components.att_router_reboot.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.att_router_reboot.models import GatewayData

from .conftest import (
    BROADBAND,
    ENTRY_DATA,
    HOST,
    MAC,
    MODEL,
    REBOOT,
    UPTIME,
    WAN_IP,
    broadband,
)

BUTTON = "button.at_t_gateway_reboot"
UPTIME_SENSOR = "sensor.at_t_gateway_uptime"
WAN_SENSOR = "binary_sensor.at_t_gateway_internet_connection"
WAN_IP_SENSOR = "sensor.at_t_gateway_wan_ip_address"
REACHABLE = "binary_sensor.at_t_gateway_reachable"


async def _setup(hass, entry, gateway, uptime=1000, up=True):
    entry.add_to_hass(hass)
    gateway.uptime.return_value = uptime
    gateway.broadband.return_value = broadband(up)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _poll(hass, entry) -> None:
    """Run the coordinator's poll, as the two-minute timer would."""
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def _reauth_flows(hass, entry):
    return [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"].get("source") == SOURCE_REAUTH
        and flow["context"].get("entry_id") == entry.entry_id
    ]


async def test_setup_creates_the_entities(hass, config_entry, gateway):
    await _setup(hass, config_entry, gateway)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(BUTTON) is not None
    assert hass.states.get(UPTIME_SENSOR).state == "1000"
    assert hass.states.get(WAN_SENSOR).state == "on"
    assert hass.states.get(WAN_IP_SENSOR).state == WAN_IP
    assert hass.states.get(REACHABLE).state == "on"


async def test_the_session_keeps_cookies_from_the_ip_host(hass, config_entry, gateway):
    """Checked by effect on the jar Home Assistant handed the client: a cookie
    set by the gateway's IP must come back on the next request."""
    await _setup(hass, config_entry, gateway)
    jar = config_entry.runtime_data.client.session.cookie_jar
    assert isinstance(jar, CookieJar)
    url = URL(f"https://{HOST}/cgi-bin/restart.ha")
    jar.update_cookies({"SessionID": "abc"}, url)
    assert set(jar.filter_cookies(url)) == {"SessionID"}


async def test_the_session_is_closed_when_the_entry_unloads(
    hass, config_entry, gateway
):
    await _setup(hass, config_entry, gateway)
    session = config_entry.runtime_data.client.session
    assert not session.closed
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert session.closed


async def test_wan_sensor_follows_the_broadband_state(hass, config_entry, gateway):
    await _setup(hass, config_entry, gateway, up=False)
    assert hass.states.get(WAN_SENSOR).state == "off"


async def test_pressing_the_button_reboots(hass, config_entry, gateway):
    await _setup(hass, config_entry, gateway)
    with patch(REBOOT, AsyncMock()) as reboot, patch(UPTIME, return_value=5):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": BUTTON},
            blocking=True,
        )
    reboot.assert_awaited_once()


async def test_a_failed_reboot_surfaces_as_an_error(hass, config_entry, gateway):
    await _setup(hass, config_entry, gateway)
    with (
        patch(REBOOT, AsyncMock(side_effect=AttRouterError("no"))),
        pytest.raises(HomeAssistantError) as info,
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": BUTTON}, blocking=True
        )
    assert info.value.translation_key == "reboot_failed"
    assert not _reauth_flows(hass, config_entry)


async def test_a_rejected_code_on_reboot_starts_reauth(hass, config_entry, gateway):
    """The one place the code is actually used is the reboot, so this is where
    a changed code shows up. The user gets a reauth prompt, not a log line."""
    await _setup(hass, config_entry, gateway)
    with (
        patch(REBOOT, AsyncMock(side_effect=AttRouterAuthError("rejected"))),
        pytest.raises(HomeAssistantError) as info,
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": BUTTON}, blocking=True
        )
    await hass.async_block_till_done()
    assert info.value.translation_key == "auth_failed"
    flows = _reauth_flows(hass, config_entry)
    assert len(flows) == 1
    assert flows[0]["step_id"] == "reauth_confirm"


async def test_a_second_rejection_does_not_open_a_second_reauth_flow(
    hass, config_entry, gateway
):
    await _setup(hass, config_entry, gateway)
    for _ in range(2):
        with (
            patch(REBOOT, AsyncMock(side_effect=AttRouterAuthError("rejected"))),
            pytest.raises(HomeAssistantError),
        ):
            await hass.services.async_call(DOMAIN, SERVICE_REBOOT, {}, blocking=True)
        await hass.async_block_till_done()
    assert len(_reauth_flows(hass, config_entry)) == 1


async def test_the_reboot_action_is_registered_and_works(hass, config_entry, gateway):
    await _setup(hass, config_entry, gateway)
    assert hass.services.has_service(DOMAIN, SERVICE_REBOOT)
    with patch(REBOOT, AsyncMock()) as reboot, patch(UPTIME, return_value=5):
        await hass.services.async_call(DOMAIN, SERVICE_REBOOT, {}, blocking=True)
    reboot.assert_awaited_once()


async def test_the_action_refuses_cleanly_while_the_entry_is_unloaded(
    hass, config_entry, gateway
):
    await _setup(hass, config_entry, gateway)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    # Registered at component setup, so it is still there to refuse cleanly.
    assert hass.services.has_service(DOMAIN, SERVICE_REBOOT)
    with (
        patch(REBOOT, AsyncMock()) as reboot,
        pytest.raises(ServiceValidationError) as info,
    ):
        await hass.services.async_call(DOMAIN, SERVICE_REBOOT, {}, blocking=True)
    assert info.value.translation_key == "not_loaded"
    reboot.assert_not_awaited()


async def test_an_unreachable_gateway_retries_with_a_translated_reason(
    hass, config_entry
):
    config_entry.add_to_hass(hass)
    with (
        patch(UPTIME, side_effect=AttRouterConnectionError("down")),
        patch(MODEL, return_value={}),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    # The reason must sit on the ConfigEntryNotReady itself: the released core
    # never looks at its cause, so the card would otherwise show nothing.
    assert config_entry.error_reason_translation_key == "cannot_connect"
    assert config_entry.error_reason_translation_placeholders == {"error": "down"}


async def test_an_unreadable_page_at_setup_retries(hass, config_entry):
    config_entry.add_to_hass(hass)
    with (
        patch(UPTIME, side_effect=AttRouterError("no uptime on the page")),
        patch(MODEL, return_value={}),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert config_entry.error_reason_translation_key == "update_failed"
    assert config_entry.error_reason_translation_placeholders == {
        "error": "no uptime on the page"
    }


async def test_losing_the_gateway_marks_entities_unavailable_but_not_reachable(
    hass, config_entry, gateway
):
    """Reachable stays available so the fault itself is visible."""
    await _setup(hass, config_entry, gateway)
    with patch(UPTIME, side_effect=AttRouterConnectionError("down")):
        await _poll(hass, config_entry)
    assert hass.states.get(UPTIME_SENSOR).state == STATE_UNAVAILABLE
    assert hass.states.get(WAN_SENSOR).state == STATE_UNAVAILABLE
    assert hass.states.get(REACHABLE).state == "off"

    with (
        patch(UPTIME, return_value=2000),
        patch(BROADBAND, return_value=broadband()),
    ):
        await _poll(hass, config_entry)
    assert hass.states.get(UPTIME_SENSOR).state == "2000"
    assert hass.states.get(REACHABLE).state == "on"


async def test_unload_removes_the_entities(hass, config_entry, gateway):
    await _setup(hass, config_entry, gateway)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_a_broadband_read_failure_does_not_fail_the_poll(hass, config_entry):
    """Uptime is what setup needs; stats are a bonus and must not block it."""
    config_entry.add_to_hass(hass)
    with (
        patch(UPTIME, return_value=1000),
        patch(MODEL, return_value={}),
        patch(BROADBAND, side_effect=AttRouterError("stats page moved")),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(UPTIME_SENSOR).state == "1000"


async def test_a_broadband_failure_on_a_later_poll_keeps_the_last_stats(
    hass, config_entry, gateway
):
    await _setup(hass, config_entry, gateway)
    with (
        patch(UPTIME, return_value=1120),
        patch(BROADBAND, side_effect=AttRouterError("stats page moved")),
    ):
        await _poll(hass, config_entry)
    assert hass.states.get(UPTIME_SENSOR).state == "1120"
    assert hass.states.get(WAN_IP_SENSOR).state == WAN_IP


async def test_data_payload_shape(hass, config_entry, gateway):
    await _setup(hass, config_entry, gateway)
    data = config_entry.runtime_data.data
    assert isinstance(data, GatewayData)
    assert data.uptime == 1000
    assert data.broadband.speed_mbps == 1000


async def test_a_setup_failure_with_no_translated_cause_is_left_alone(
    hass, config_entry, gateway
):
    """The lifting in async_setup_entry applies only to a cause that carries a
    key; anything else must reach core exactly as it was raised."""
    config_entry.add_to_hass(hass)
    with patch(
        "custom_components.att_router_reboot.coordinator.AttRouterCoordinator"
        ".async_config_entry_first_refresh",
        side_effect=ConfigEntryNotReady("something else entirely"),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert config_entry.error_reason_translation_key is None


async def test_a_model_lookup_failure_does_not_block_setup(hass, config_entry, gateway):
    """Model, serial and firmware only enrich the device page; uptime is what
    the entities need, so a miss there must not fail the entry."""
    gateway.model.side_effect = AttRouterError("sysinfo moved")
    await _setup(hass, config_entry, gateway)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(UPTIME_SENSOR).state == "1000"


async def test_changing_the_options_reloads_the_entry(hass, config_entry, gateway):
    """The schedule is wired at setup, so an options change has to reload."""
    await _setup(hass, config_entry, gateway)
    first = config_entry.runtime_data
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_SCHEDULE: SCHEDULE_DAILY}
    )
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data is not first


async def test_diagnostics_redact_what_identifies_the_household(
    hass, config_entry, gateway
):
    await _setup(hass, config_entry, gateway)
    report = await async_get_config_entry_diagnostics(hass, config_entry)
    dumped = str(report)
    assert ENTRY_DATA["access_code"] not in dumped
    assert HOST not in dumped
    assert WAN_IP not in dumped
    assert MAC not in dumped
    # What is left is still useful.
    assert report["data"]["uptime"] == 1000
    assert report["data"]["broadband"]["speed_mbps"] == 1000
    assert report["model_info"]["model"] == "BGW320-500"
    assert report["last_update_success"] is True


async def test_diagnostics_redact_the_options_as_well_as_the_data(
    hass, config_entry, gateway
):
    """A key that identifies the household does so wherever it is stored."""
    await _setup(hass, config_entry, gateway)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_SCHEDULE: SCHEDULE_DAILY, CONF_HOST: HOST}
    )
    await hass.async_block_till_done()
    report = await async_get_config_entry_diagnostics(hass, config_entry)
    assert HOST not in str(report)
    assert report["options"][CONF_SCHEDULE] == SCHEDULE_DAILY
