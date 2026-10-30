"""Each setup screen submitted the way the dialog sends it.

The data comes from the schema the frontend receives, through a port of its
initial-data code (frontend_form.py); Advanced is never opened.
"""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType

from custom_components.att_router_reboot.api import (
    AttRouterAuthError,
    AttRouterConnectionError,
)
from custom_components.att_router_reboot.const import (
    CONF_ACCESS_CODE,
    CONF_ADVANCED,
    DOMAIN,
)

from .conftest import ENTRY_DATA
from .frontend_form import frontend_submission

VERIFY = (
    "custom_components.att_router_reboot.api.AttRouterClient.async_verify_access_code"
)
CODE = {CONF_ACCESS_CODE: ENTRY_DATA[CONF_ACCESS_CODE]}


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """The flow only; the setup it triggers is tested in test_init."""
    with patch(
        "custom_components.att_router_reboot.async_setup_entry", return_value=True
    ):
        yield


async def _first_screen(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"
    return result


async def _schedule_finishes(hass, result) -> None:
    """The last step, the schedule, submitted as it opened."""
    assert result["step_id"] == "schedule"
    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], frontend_submission(result)
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"] == ENTRY_DATA


async def test_the_first_screen_submits_with_advanced_collapsed(hass):
    result = await _first_screen(hass)
    with patch(VERIFY, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], frontend_submission(result, CODE)
        )
    await _schedule_finishes(hass, result)


async def test_the_first_screen_shown_again_after_an_error_submits(hass):
    result = await _first_screen(hass)
    with patch(VERIFY, side_effect=AttRouterAuthError("no")):
        shown = await hass.config_entries.flow.async_configure(
            result["flow_id"], frontend_submission(result, CODE)
        )
    assert shown["step_id"] == "user"
    assert shown["errors"] == {"base": "invalid_auth"}

    # The code is not echoed back, so it is typed again; Advanced is left alone.
    with patch(VERIFY, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            shown["flow_id"], frontend_submission(shown, CODE)
        )
    await _schedule_finishes(hass, result)


async def test_the_unreachable_step_submits_as_it_opened(hass):
    result = await _first_screen(hass)
    with patch(VERIFY, side_effect=AttRouterConnectionError("down")):
        shown = await hass.config_entries.flow.async_configure(
            result["flow_id"], frontend_submission(result, CODE)
        )
    assert shown["step_id"] == "unreachable"

    # Submit alone checks again with the same code.
    with patch(VERIFY, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            shown["flow_id"], frontend_submission(shown)
        )
    await _schedule_finishes(hass, result)


async def test_what_was_typed_in_advanced_comes_back_after_an_error(hass):
    result = await _first_screen(hass)
    sent = frontend_submission(result, CODE)
    sent[CONF_ADVANCED][CONF_HOST] = "192.0.2.9"
    with patch(VERIFY, side_effect=AttRouterAuthError("no")):
        shown = await hass.config_entries.flow.async_configure(result["flow_id"], sent)
    assert shown["errors"] == {"base": "invalid_auth"}

    # The section reopens holding the typed address, and Submit sends it back.
    again = frontend_submission(shown, CODE)
    assert again[CONF_ADVANCED][CONF_HOST] == "192.0.2.9"
    hass.config_entries.flow.async_abort(shown["flow_id"])
