"""The config flow: setup, its failures, reconfigure, reauth, and the options."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType

from custom_components.att_router_reboot.api import (
    AttRouterAuthError,
    AttRouterConnectionError,
    AttRouterError,
)
from custom_components.att_router_reboot.const import (
    CONF_ACCESS_CODE,
    CONF_SCHEDULE,
    CONF_SCHEDULE_TIME,
    CONF_SCHEDULE_WEEKDAY,
    DOMAIN,
    SCHEDULE_DAILY,
    SCHEDULE_OFF,
    SCHEDULE_WEEKLY,
)

from .conftest import ENTRY_DATA, HOST

VERIFY = (
    "custom_components.att_router_reboot.api.AttRouterClient.async_verify_access_code"
)


async def test_user_step_creates_the_entry(hass):
    with patch(VERIFY, return_value=None):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=dict(ENTRY_DATA)
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == HOST
    assert result["result"].unique_id == HOST


async def test_the_first_form_is_shown_with_no_input(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (AttRouterAuthError("no"), "invalid_auth"),
        (AttRouterConnectionError("down"), "cannot_connect"),
        (AttRouterError("weird"), "unknown"),
    ],
)
async def test_each_failure_maps_to_its_message(hass, raised, expected):
    with patch(VERIFY, side_effect=raised):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=dict(ENTRY_DATA)
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_the_same_gateway_cannot_be_added_twice(hass, config_entry):
    config_entry.add_to_hass(hass)
    with patch(VERIFY, return_value=None):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=dict(ENTRY_DATA)
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_reconfigure_updates_the_access_code(hass, config_entry):
    config_entry.add_to_hass(hass)
    with patch(VERIFY, return_value=None):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": config_entry.entry_id},
            data={**ENTRY_DATA, CONF_ACCESS_CODE: "newcode"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_ACCESS_CODE] == "newcode"


async def test_reconfigure_refuses_a_different_gateway(hass, config_entry):
    config_entry.add_to_hass(hass)
    with patch(VERIFY, return_value=None):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": config_entry.entry_id},
            data={**ENTRY_DATA, CONF_HOST: "10.0.0.1"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "another_gateway"
    assert config_entry.data[CONF_HOST] == HOST


async def test_reauth_updates_only_the_code(hass, config_entry):
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with patch(VERIFY, return_value=None):
        done = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ACCESS_CODE: "reauthed"}
        )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reauth_successful"
    assert config_entry.data[CONF_ACCESS_CODE] == "reauthed"
    assert config_entry.data[CONF_HOST] == HOST


async def test_options_flow_sets_a_daily_schedule(hass, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["step_id"] == "init"
    done = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCHEDULE: SCHEDULE_DAILY, CONF_SCHEDULE_TIME: "03:30:00"},
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_SCHEDULE] == SCHEDULE_DAILY
    assert config_entry.options[CONF_SCHEDULE_TIME] == "03:30:00"


async def test_options_off_drops_the_time(hass, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    done = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCHEDULE: SCHEDULE_OFF}
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_SCHEDULE_TIME not in config_entry.options


async def test_options_weekly_keeps_the_weekday(hass, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    done = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCHEDULE: SCHEDULE_WEEKLY,
            CONF_SCHEDULE_TIME: "04:00:00",
            CONF_SCHEDULE_WEEKDAY: "sunday",
        },
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_SCHEDULE_WEEKDAY] == "sunday"
