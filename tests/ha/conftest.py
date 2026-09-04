"""Fixtures for the Home Assistant layer tests.

In its own directory so the autouse fixture does not attach to the pure parser
and API suites one level up, which need no Home Assistant.
"""

import pathlib

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_HOST
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.att_router_reboot.const import (
    CONF_ACCESS_CODE,
    CONF_VERIFY_SSL,
    DOMAIN,
)

HOST = "192.168.1.254"
FIX = pathlib.Path(__file__).resolve().parent.parent / "fixtures"

ENTRY_DATA = {
    CONF_HOST: HOST,
    CONF_ACCESS_CODE: "secret42",
    CONF_VERIFY_SSL: False,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Required for Home Assistant to load a custom component in tests."""
    return


@pytest.fixture
def config_entry():
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"AT&T Gateway ({HOST})",
        unique_id=HOST,
        data=dict(ENTRY_DATA),
    )


@pytest.fixture
def sysinfo_html() -> str:
    return (FIX / "sysinfo.html").read_text(encoding="utf-8")


@pytest.fixture
def broadband_html() -> str:
    return (FIX / "broadbandstatistics.html").read_text(encoding="utf-8")
