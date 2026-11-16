"""Fixtures for the Home Assistant layer tests.

In its own directory so the autouse fixtures do not attach to the pure parser
and API suites one level up, which need no Home Assistant.
"""

import pathlib
from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_HOST
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.att_router_reboot.const import (
    CONF_ACCESS_CODE,
    CONF_VERIFY_SSL,
    DOMAIN,
)
from custom_components.att_router_reboot.models import BroadbandStats, SysInfo

HOST = "192.168.1.254"
FIX = pathlib.Path(__file__).resolve().parent.parent / "fixtures"

ENTRY_DATA = {
    CONF_HOST: HOST,
    CONF_ACCESS_CODE: "secret42",
    CONF_VERIFY_SSL: False,
}

WAN_IP = "203.0.113.10"
MAC = "aa:bb:cc:dd:ee:ff"
SERIAL = "001E46-A1B2C3D4E5F6"
FIRMWARE = "6.35.8"
MODEL_INFO = {
    "model": "BGW320-500",
    "serial": SERIAL,
    "mac": MAC,
    "firmware": FIRMWARE,
}

CLIENT = "custom_components.att_router_reboot.api.AttRouterClient"
SYSINFO = f"{CLIENT}.async_get_sysinfo"
MODEL = f"{CLIENT}.async_get_model"
BROADBAND = f"{CLIENT}.async_get_broadband"
REBOOT = f"{CLIENT}.async_reboot"


def sysinfo(uptime: int, firmware: str | None = FIRMWARE) -> SysInfo:
    """What the system information page yields for one poll."""
    info = dict(MODEL_INFO)
    if firmware is None:
        info.pop("firmware")
    else:
        info["firmware"] = firmware
    return SysInfo(uptime=uptime, info=info)


def broadband(up: bool = True) -> BroadbandStats:
    return BroadbandStats(
        connection_up=up,
        connection_source="ETHERNET",
        ipv4_address=WAN_IP,
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


@dataclass
class Gateway:
    """The client's three read calls, mocked for the life of a test.

    `uptime` and `firmware` feed the one system information read; set
    `firmware` to None to model a page that does not carry it.
    """

    uptime: AsyncMock
    model: AsyncMock
    broadband: AsyncMock
    firmware: dict[str, str | None]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Required for Home Assistant to load a custom component in tests."""
    return


@pytest.fixture(autouse=True)
def gateway() -> Iterator[Gateway]:
    """Keep every read off the network for the whole test, not just setup.

    The coordinator polls on its own timer and refreshes after a reboot, so a
    patch that ends when setup ends leaves the next read to a real socket,
    which the harness blocks. Tests adjust return_value and side_effect here.
    """
    uptime = AsyncMock(return_value=1000)
    firmware: dict[str, str | None] = {"value": FIRMWARE}

    async def read_sysinfo(*_: object) -> SysInfo:
        return sysinfo(await uptime(), firmware["value"])

    with (
        patch(SYSINFO, side_effect=read_sysinfo),
        patch(MODEL, return_value=dict(MODEL_INFO)) as model,
        patch(BROADBAND, return_value=broadband()) as stats,
    ):
        yield Gateway(uptime=uptime, model=model, broadband=stats, firmware=firmware)


@pytest.fixture
def config_entry():
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"AT&T Gateway ({HOST})",
        unique_id=SERIAL,
        data=dict(ENTRY_DATA),
    )


@pytest.fixture
def sysinfo_html() -> str:
    return (FIX / "sysinfo.html").read_text(encoding="utf-8")


@pytest.fixture
def broadband_html() -> str:
    return (FIX / "broadbandstatistics.html").read_text(encoding="utf-8")
