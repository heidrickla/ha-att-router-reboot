"""The config flow: setup, its failures and recovery, reconfigure, reauth, options."""

from unittest.mock import patch

import pytest
import voluptuous as vol
from aiohttp import CookieJar
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType
from yarl import URL

from custom_components.att_router_reboot.api import (
    AttRouterAuthError,
    AttRouterClient,
    AttRouterConnectionError,
    AttRouterError,
)
from custom_components.att_router_reboot.const import (
    CONF_ACCESS_CODE,
    CONF_SCHEDULE,
    CONF_SCHEDULE_TIME,
    CONF_SCHEDULE_WEEKDAY,
    CONF_VERIFY_SSL,
    DOMAIN,
    SCHEDULE_DAILY,
    SCHEDULE_OFF,
    SCHEDULE_WEEKLY,
)

from .conftest import ENTRY_DATA, HOST

VERIFY = (
    "custom_components.att_router_reboot.api.AttRouterClient.async_verify_access_code"
)


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """These tests are about the flow; the setup it triggers is tested in
    test_init and would otherwise reach for the gateway when the entry is
    created or reloaded."""
    with patch(
        "custom_components.att_router_reboot.async_setup_entry", return_value=True
    ):
        yield


def _access_code_field(result):
    for key in result["data_schema"].schema:
        if key == CONF_ACCESS_CODE:
            return key
    pytest.fail("no access code field on the form")


def _assert_no_secret_shown(result):
    """Neither a default nor a suggested value may carry the access code."""
    key = _access_code_field(result)
    assert (key.description or {}).get("suggested_value") in (None, "")
    # A Marker's default is UNDEFINED when none was given, else a factory.
    assert key.default is vol.UNDEFINED or key.default() in (None, "")


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
    _assert_no_secret_shown(result)


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (AttRouterAuthError("no"), "invalid_auth"),
        (AttRouterConnectionError("down"), "cannot_connect"),
        (AttRouterError("weird"), "unknown"),
    ],
)
async def test_each_failure_maps_to_its_message_and_the_flow_recovers(
    hass, raised, expected
):
    with patch(VERIFY, side_effect=raised):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=dict(ENTRY_DATA)
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    # The typed code is not echoed back into the form.
    _assert_no_secret_shown(result)

    # Fix the problem and resubmit on the same flow: it must finish.
    with patch(VERIFY, return_value=None):
        done = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(ENTRY_DATA)
        )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"] == ENTRY_DATA


async def test_the_flow_talks_to_the_gateway_through_an_unsafe_cookie_jar(hass):
    """The session the flow validates with must keep cookies from an IP host,
    otherwise the gateway serves its cookies-disabled stub and no code can
    ever validate. Checked by effect on the real jar, not by type."""
    seen = {}

    async def _capture(self: AttRouterClient) -> None:
        jar = self.session.cookie_jar
        url = URL(f"https://{HOST}/cgi-bin/restart.ha")
        jar.update_cookies({"SessionID": "abc"}, url)
        seen["kept"] = set(jar.filter_cookies(url))
        seen["jar"] = jar

    with patch(VERIFY, _capture):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=dict(ENTRY_DATA)
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert isinstance(seen["jar"], CookieJar)
    assert seen["kept"] == {"SessionID"}


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
    await hass.async_block_till_done()


async def test_reconfigure_form_does_not_carry_the_stored_access_code(
    hass, config_entry
):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": config_entry.entry_id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    _assert_no_secret_shown(result)
    # The host is suggested, so the user sees what they are reconfiguring.
    for key in result["data_schema"].schema:
        if key == CONF_HOST:
            assert (key.description or {}).get("suggested_value") == HOST


async def test_reconfigure_with_a_blank_code_keeps_the_stored_one(hass, config_entry):
    config_entry.add_to_hass(hass)
    validated = {}

    async def _record(self: AttRouterClient) -> None:
        validated["code"] = self._access_code

    with patch(VERIFY, _record):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": config_entry.entry_id},
            data={CONF_HOST: HOST, CONF_VERIFY_SSL: True},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    # The stored code was what got validated, and it is still stored.
    assert validated["code"] == ENTRY_DATA[CONF_ACCESS_CODE]
    assert config_entry.data[CONF_ACCESS_CODE] == ENTRY_DATA[CONF_ACCESS_CODE]
    assert config_entry.data[CONF_VERIFY_SSL] is True
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (AttRouterAuthError("no"), "invalid_auth"),
        (AttRouterConnectionError("down"), "cannot_connect"),
        (AttRouterError("weird"), "unknown"),
    ],
)
async def test_reconfigure_shows_each_error_and_then_recovers(
    hass, config_entry, raised, expected
):
    config_entry.add_to_hass(hass)
    with patch(VERIFY, side_effect=raised):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": config_entry.entry_id},
            data={**ENTRY_DATA, CONF_ACCESS_CODE: "wrong"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    _assert_no_secret_shown(result)
    assert config_entry.data[CONF_ACCESS_CODE] == ENTRY_DATA[CONF_ACCESS_CODE]

    with patch(VERIFY, return_value=None):
        done = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**ENTRY_DATA, CONF_ACCESS_CODE: "right"}
        )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_ACCESS_CODE] == "right"
    await hass.async_block_till_done()


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
    _assert_no_secret_shown(result)
    with patch(VERIFY, return_value=None):
        done = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ACCESS_CODE: "reauthed"}
        )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reauth_successful"
    assert config_entry.data[CONF_ACCESS_CODE] == "reauthed"
    assert config_entry.data[CONF_HOST] == HOST
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (AttRouterAuthError("no"), "invalid_auth"),
        (AttRouterConnectionError("down"), "cannot_connect"),
        (AttRouterError("weird"), "unknown"),
    ],
)
async def test_reauth_shows_each_error_and_then_recovers(
    hass, config_entry, raised, expected
):
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    with patch(VERIFY, side_effect=raised):
        again = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ACCESS_CODE: "wrong"}
        )
    assert again["type"] is FlowResultType.FORM
    assert again["errors"] == {"base": expected}
    assert config_entry.data[CONF_ACCESS_CODE] == ENTRY_DATA[CONF_ACCESS_CODE]

    with patch(VERIFY, return_value=None):
        done = await hass.config_entries.flow.async_configure(
            again["flow_id"], {CONF_ACCESS_CODE: "right"}
        )
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reauth_successful"
    assert config_entry.data[CONF_ACCESS_CODE] == "right"
    await hass.async_block_till_done()


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


async def test_options_daily_drops_the_weekday(hass, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    done = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCHEDULE: SCHEDULE_DAILY,
            CONF_SCHEDULE_TIME: "04:00:00",
            CONF_SCHEDULE_WEEKDAY: "monday",
        },
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_SCHEDULE_WEEKDAY not in config_entry.options
