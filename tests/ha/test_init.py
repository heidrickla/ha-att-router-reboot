"""Setup, entities, the reboot action, and the schedule guard."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError

from custom_components.att_router_reboot.const import DOMAIN, SERVICE_REBOOT
from custom_components.att_router_reboot.models import BroadbandStats, GatewayData

UPTIME = "custom_components.att_router_reboot.api.AttRouterClient.async_get_uptime"
MODEL = "custom_components.att_router_reboot.api.AttRouterClient.async_get_model"
BROADBAND = (
    "custom_components.att_router_reboot.api.AttRouterClient.async_get_broadband"
)
REBOOT = "custom_components.att_router_reboot.api.AttRouterClient.async_reboot"

BUTTON = "button.at_t_gateway_reboot"
UPTIME_SENSOR = "sensor.at_t_gateway_uptime"
WAN_SENSOR = "binary_sensor.at_t_gateway_internet_connection"


def _broadband(up=True):
    return BroadbandStats(
        connection_up=up,
        connection_source="ETHERNET",
        ipv4_address="203.0.113.10",
        line_state="Up",
        speed_mbps=1000,
        duplex="full",
        rx_bytes=100,
        tx_bytes=200,
        rx_packets=3,
        tx_packets=4,
        rx_errors=0,
        tx_errors=0,
    )


async def _setup(hass, entry, uptime=1000, up=True):
    entry.add_to_hass(hass)
    with (
        patch(UPTIME, return_value=uptime),
        patch(MODEL, return_value={"model": "BGW320-500", "mac": "aa:bb:cc:dd:ee:ff"}),
        patch(BROADBAND, return_value=_broadband(up)),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_setup_creates_the_entities(hass, config_entry):
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(BUTTON) is not None
    assert hass.states.get(UPTIME_SENSOR).state == "1000"
    assert hass.states.get(WAN_SENSOR).state == "on"


async def test_wan_sensor_follows_the_broadband_state(hass, config_entry):
    await _setup(hass, config_entry, up=False)
    assert hass.states.get(WAN_SENSOR).state == "off"


async def test_pressing_the_button_reboots(hass, config_entry):
    await _setup(hass, config_entry)
    with patch(REBOOT, AsyncMock()) as reboot, patch(UPTIME, return_value=5):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": BUTTON},
            blocking=True,
        )
    reboot.assert_awaited_once()


async def test_a_failed_reboot_surfaces_as_an_error(hass, config_entry):
    from custom_components.att_router_reboot.api import AttRouterError

    await _setup(hass, config_entry)
    with (
        patch(REBOOT, AsyncMock(side_effect=AttRouterError("no"))),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": BUTTON}, blocking=True
        )


async def test_the_reboot_action_is_registered_and_works(hass, config_entry):
    await _setup(hass, config_entry)
    assert hass.services.has_service(DOMAIN, SERVICE_REBOOT)
    with patch(REBOOT, AsyncMock()) as reboot, patch(UPTIME, return_value=5):
        await hass.services.async_call(DOMAIN, SERVICE_REBOOT, {}, blocking=True)
    reboot.assert_awaited_once()


async def test_the_action_survives_the_entry_being_unloaded(hass, config_entry):
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    # Registered at component setup, so it is still there to refuse cleanly.
    assert hass.services.has_service(DOMAIN, SERVICE_REBOOT)


async def test_an_unreachable_gateway_retries(hass, config_entry):
    from custom_components.att_router_reboot.api import AttRouterConnectionError

    config_entry.add_to_hass(hass)
    with (
        patch(UPTIME, side_effect=AttRouterConnectionError("down")),
        patch(MODEL, return_value={}),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_removes_the_entities(hass, config_entry):
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_a_broadband_read_failure_does_not_fail_the_poll(hass, config_entry):
    """Uptime is what setup needs; stats are a bonus and must not block it."""
    from custom_components.att_router_reboot.api import AttRouterError

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


async def test_data_payload_shape(hass, config_entry):
    await _setup(hass, config_entry)
    data = config_entry.runtime_data.data
    assert isinstance(data, GatewayData)
    assert data.uptime == 1000
    assert data.broadband.speed_mbps == 1000
