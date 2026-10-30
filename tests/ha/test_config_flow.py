"""The config flow: setup, its failures and recovery, reconfigure, reauth, options."""

from unittest.mock import patch

import pytest
import voluptuous as vol
from aiohttp import CookieJar
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResultType, section
from yarl import URL

from custom_components.att_router_reboot.api import (
    AttRouterAuthError,
    AttRouterClient,
    AttRouterConnectionError,
    AttRouterError,
)
from custom_components.att_router_reboot.const import (
    CONF_ACCESS_CODE,
    CONF_ADVANCED,
    CONF_SCHEDULE,
    CONF_SCHEDULE_TIME,
    CONF_SCHEDULE_WEEKDAY,
    CONF_VERIFY_SSL,
    DOMAIN,
    SCHEDULE_DAILY,
    SCHEDULE_OFF,
    SCHEDULE_WEEKLY,
)

from .conftest import ENTRY_DATA, HOST, MAC, SERIAL

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


def setup_input(code=ENTRY_DATA[CONF_ACCESS_CODE], **advanced):
    """The first screen's input: the code, and host and certificate in Advanced."""
    return {
        CONF_ACCESS_CODE: code,
        CONF_ADVANCED: {
            CONF_HOST: ENTRY_DATA[CONF_HOST],
            CONF_VERIFY_SSL: ENTRY_DATA[CONF_VERIFY_SSL],
            **advanced,
        },
    }


async def start(hass, user_input=None, side_effect=None):
    with patch(VERIFY, return_value=None, side_effect=side_effect):
        return await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=user_input or setup_input()
        )


async def finish(hass, result, schedule=None):
    """Submit the last step, the schedule, as offered unless told otherwise."""
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "schedule"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], schedule or {}
    )


def _field(schema, name):
    for key in schema.schema:
        if key == name:
            return key
    pytest.fail(f"no {name} field on the form")


def _assert_no_secret_shown(result):
    """Neither a default nor a suggested value may carry the access code."""
    key = _field(result["data_schema"], CONF_ACCESS_CODE)
    assert (key.description or {}).get("suggested_value") in (None, "")
    # A Marker's default is UNDEFINED when none was given, else a factory.
    assert key.default is vol.UNDEFINED or key.default() in (None, "")


def _advanced(result):
    """The Advanced section of the first screen."""
    value = result["data_schema"].schema[_field(result["data_schema"], CONF_ADVANCED)]
    assert isinstance(value, section)
    return value


async def test_user_step_creates_the_entry(hass):
    result = await finish(hass, await start(hass))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == ENTRY_DATA
    assert result["title"] == f"AT&T Gateway ({HOST})"
    assert result["result"].unique_id == SERIAL
    assert result["options"] == {CONF_SCHEDULE: SCHEDULE_OFF}


async def test_the_first_screen_asks_only_for_the_access_code(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert list(result["data_schema"].schema) == [CONF_ACCESS_CODE, CONF_ADVANCED]
    _assert_no_secret_shown(result)
    advanced = _advanced(result)
    assert advanced.options["collapsed"] is True
    assert [str(k) for k in advanced.schema.schema] == [CONF_HOST, CONF_VERIFY_SSL]
    assert _field(advanced.schema, CONF_HOST).default() == HOST
    assert _field(advanced.schema, CONF_VERIFY_SSL).default() is False


async def test_the_access_code_alone_sets_up_the_default_gateway(hass):
    """Advanced untouched: AT&T's address and no certificate check."""
    seen = {}

    async def _record(self: AttRouterClient) -> None:
        seen["host"] = self._host
        seen["code"] = self._access_code

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(VERIFY, _record):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ACCESS_CODE: "secret42"}
        )
    assert seen == {"host": HOST, "code": "secret42"}
    done = await finish(hass, result)
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"] == ENTRY_DATA


async def test_the_entry_is_keyed_on_the_mac_when_there_is_no_serial(hass, gateway):
    gateway.model.return_value = {"model": "BGW320-500", "mac": "AA:BB:CC:DD:EE:FF"}
    result = await finish(hass, await start(hass))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == MAC


async def test_a_gateway_reporting_no_identity_is_refused(hass, gateway):
    """Without a serial or MAC there is nothing but the address to key on."""
    gateway.model.return_value = {"model": "BGW320-500"}
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "unknown"}


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (AttRouterAuthError("no"), "invalid_auth"),
        (AttRouterError("weird"), "unknown"),
    ],
)
async def test_each_failure_maps_to_its_message_and_the_flow_recovers(
    hass, raised, expected
):
    with patch(VERIFY, side_effect=raised):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data=setup_input(**{CONF_HOST: "10.0.0.1", CONF_VERIFY_SSL: True}),
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": expected}
    # The typed code is not echoed back; Advanced opens with what was typed.
    _assert_no_secret_shown(result)
    advanced = _advanced(result)
    assert advanced.options["collapsed"] is False
    host = _field(advanced.schema, CONF_HOST)
    assert host.description == {"suggested_value": "10.0.0.1"}
    verify = _field(advanced.schema, CONF_VERIFY_SSL)
    assert verify.description == {"suggested_value": True}

    # Fix the problem and resubmit on the same flow: it must finish.
    with patch(VERIFY, return_value=None):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], setup_input()
        )
    done = await finish(hass, result)
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"] == ENTRY_DATA


async def test_an_unreachable_gateway_gets_a_step_that_checks_again(hass):
    """The step says what to check, keeps the typed code, and Submit retries."""
    seen = []

    async def _record(self: AttRouterClient) -> None:
        seen.append((self._host, self._access_code))

    result = await start(
        hass, setup_input("typed-code"), AttRouterConnectionError("down")
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "unreachable"
    assert result["errors"] == {}
    assert result["description_placeholders"] == {
        "host": HOST,
        "url": f"https://{HOST}/",
        "default_host": HOST,
    }
    assert [str(k) for k in result["data_schema"].schema] == [
        CONF_HOST,
        CONF_VERIFY_SSL,
    ]
    assert _field(result["data_schema"], CONF_HOST).default() == HOST

    with patch(VERIFY, side_effect=AttRouterConnectionError("down")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: HOST, CONF_VERIFY_SSL: False}
        )
    assert result["step_id"] == "unreachable"
    assert result["errors"] == {"base": "still_cannot_connect"}

    with patch(VERIFY, _record):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.1", CONF_VERIFY_SSL: False}
        )
    assert seen == [("10.0.0.1", "typed-code")]
    done = await finish(hass, result)
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["data"] == {
        CONF_HOST: "10.0.0.1",
        CONF_ACCESS_CODE: "typed-code",
        CONF_VERIFY_SSL: False,
    }
    assert done["title"] == "AT&T Gateway (10.0.0.1)"


async def test_a_code_refused_once_reachable_goes_back_to_the_first_screen(hass):
    result = await start(hass, side_effect=AttRouterConnectionError("down"))
    with patch(VERIFY, side_effect=AttRouterAuthError("no")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.1", CONF_VERIFY_SSL: False}
        )
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}
    _assert_no_secret_shown(result)
    host = _field(_advanced(result).schema, CONF_HOST)
    assert host.description == {"suggested_value": "10.0.0.1"}


async def test_an_unexpected_answer_stays_on_the_unreachable_step(hass):
    result = await start(hass, side_effect=AttRouterConnectionError("down"))
    with patch(VERIFY, side_effect=AttRouterError("weird")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: HOST, CONF_VERIFY_SSL: False}
        )
    assert result["step_id"] == "unreachable"
    assert result["errors"] == {"base": "unknown"}


async def test_the_last_step_offers_the_schedule_off(hass):
    result = await start(hass)
    schema = result["data_schema"]
    assert _field(schema, CONF_SCHEDULE).default() == SCHEDULE_OFF
    assert _field(schema, CONF_SCHEDULE_TIME).default() == "04:00:00"
    assert _field(schema, CONF_SCHEDULE_WEEKDAY).default() == "sunday"
    done = await finish(
        hass,
        result,
        {
            CONF_SCHEDULE: SCHEDULE_WEEKLY,
            CONF_SCHEDULE_TIME: "03:00:00",
            CONF_SCHEDULE_WEEKDAY: "monday",
        },
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["options"] == {
        CONF_SCHEDULE: SCHEDULE_WEEKLY,
        CONF_SCHEDULE_TIME: "03:00:00",
        CONF_SCHEDULE_WEEKDAY: "monday",
    }


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
            DOMAIN, context={"source": SOURCE_USER}, data=setup_input()
        )
    assert result["step_id"] == "schedule"
    assert isinstance(seen["jar"], CookieJar)
    assert seen["kept"] == {"SessionID"}


async def test_the_same_gateway_cannot_be_added_twice(hass, config_entry):
    config_entry.add_to_hass(hass)
    result = await start(hass)
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


async def test_reconfigure_refuses_a_different_gateway(hass, config_entry, gateway):
    config_entry.add_to_hass(hass)
    gateway.model.return_value = {"serial": "001E46-000000000000", "mac": MAC}
    with patch(VERIFY, return_value=None):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": config_entry.entry_id},
            data={**ENTRY_DATA, CONF_HOST: "10.0.0.1"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "another_gateway"
    assert config_entry.data[CONF_HOST] == HOST


async def test_reconfigure_follows_the_gateway_to_a_new_address(hass, config_entry):
    config_entry.add_to_hass(hass)
    with patch(VERIFY, return_value=None):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": config_entry.entry_id},
            data={**ENTRY_DATA, CONF_HOST: "10.0.0.1"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_HOST] == "10.0.0.1"
    assert config_entry.title == "AT&T Gateway (10.0.0.1)"
    assert config_entry.unique_id == SERIAL
    await hass.async_block_till_done()


async def test_reconfigure_keeps_a_title_the_user_chose(hass, config_entry):
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, title="Fibre gateway")
    with patch(VERIFY, return_value=None):
        await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": config_entry.entry_id},
            data={**ENTRY_DATA, CONF_HOST: "10.0.0.1"},
        )
    assert config_entry.data[CONF_HOST] == "10.0.0.1"
    assert config_entry.title == "Fibre gateway"
    await hass.async_block_till_done()


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
