"""Config flow for AT&T Router Reboot.

The first screen asks only for the access code on the gateway's label; the
address and the certificate check default to AT&T's and wait in a collapsed
section. A gateway that cannot be reached gets a step that says how to fix it
and checks again, and the last step offers the reboot schedule, off.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, override

import voluptuous as vol
from aiohttp import CookieJar
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    AttRouterAuthError,
    AttRouterClient,
    AttRouterConnectionError,
    AttRouterError,
)
from .const import (
    CONF_ACCESS_CODE,
    CONF_ADVANCED,
    CONF_SCHEDULE,
    CONF_SCHEDULE_TIME,
    CONF_SCHEDULE_WEEKDAY,
    CONF_VERIFY_SSL,
    DEFAULT_HOST,
    DEFAULT_SCHEDULE,
    DEFAULT_SCHEDULE_TIME,
    DEFAULT_SCHEDULE_WEEKDAY,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    SCHEDULE_OFF,
    SCHEDULE_WEEKLY,
    SCHEDULES,
    WEEKDAYS,
)
from .models import gateway_identity

# The access code is a credential: masked in the browser, never echoed back.
_ACCESS_CODE = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


async def _validate(hass: HomeAssistant, data: Mapping[str, Any]) -> str:
    """Log in against the real gateway and return its identity; raises on failure.

    The same session shape __init__.py uses - own jar, unsafe for the IP host -
    so the flow proves the exact conversation the reboot will have. Detached
    here rather than left to the helper, since a flow is over in seconds; the
    connector is Home Assistant's shared one, so detach is the right release.

    The identity is the unique id, so the entry follows the gateway rather
    than its address.
    """
    session = async_create_clientsession(
        hass,
        verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        auto_cleanup=False,
        cookie_jar=CookieJar(unsafe=True),
    )
    client = AttRouterClient(session, data[CONF_HOST], data[CONF_ACCESS_CODE])
    try:
        await client.async_verify_access_code()
        identity = gateway_identity(await client.async_get_model())
    finally:
        session.detach()
    if identity is None:
        raise AttRouterError("sysinfo.ha reported no serial number or MAC address")
    return identity


def _title(host: str) -> str:
    return f"AT&T Gateway ({host})"


def _connection_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Host and certificate check, each with a default a new user can keep."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, DEFAULT_HOST)): str,
            vol.Required(
                CONF_VERIFY_SSL,
                default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            ): bool,
        }
    )


def _reconfigure_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Every connection field in one form; a blank access code keeps the stored one."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, DEFAULT_HOST)): str,
            vol.Optional(CONF_ACCESS_CODE): _ACCESS_CODE,
            vol.Required(
                CONF_VERIFY_SSL,
                default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            ): bool,
        }
    )


def _schedule_schema(current: Mapping[str, Any]) -> vol.Schema:
    """The reboot schedule, shared by the last setup step and the options flow."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SCHEDULE,
                default=current.get(CONF_SCHEDULE, DEFAULT_SCHEDULE),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=SCHEDULES,
                    translation_key="schedule",
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_SCHEDULE_TIME,
                default=current.get(CONF_SCHEDULE_TIME, DEFAULT_SCHEDULE_TIME),
            ): selector.TimeSelector(),
            vol.Optional(
                CONF_SCHEDULE_WEEKDAY,
                default=current.get(CONF_SCHEDULE_WEEKDAY, DEFAULT_SCHEDULE_WEEKDAY),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=WEEKDAYS,
                    translation_key="weekday",
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _schedule_options(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Drop the fields the chosen schedule does not use."""
    cleaned = dict(user_input)
    if cleaned.get(CONF_SCHEDULE) != SCHEDULE_WEEKLY:
        cleaned.pop(CONF_SCHEDULE_WEEKDAY, None)
    if cleaned.get(CONF_SCHEDULE) == SCHEDULE_OFF:
        cleaned.pop(CONF_SCHEDULE_TIME, None)
    return cleaned


class AttRouterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup, reconfigure and reauth for the gateway."""

    VERSION = 1

    def __init__(self) -> None:
        # Held on the server between steps, so the typed code never goes back out.
        self._data: dict[str, Any] = {}

    async def _async_try(
        self, data: Mapping[str, Any]
    ) -> tuple[str | None, dict[str, str]]:
        """The gateway's identity, or the form error to show."""
        try:
            return await _validate(self.hass, data), {}
        except AttRouterAuthError:
            return None, {"base": "invalid_auth"}
        except AttRouterConnectionError:
            return None, {"base": "cannot_connect"}
        except AttRouterError:
            return None, {"base": "unknown"}

    async def _async_found(self, identity: str) -> ConfigFlowResult:
        await self.async_set_unique_id(identity)
        self._abort_if_unique_id_configured()
        return await self.async_step_schedule()

    def _user_form(self, errors: dict[str, str]) -> ConfigFlowResult:
        schema = vol.Schema(
            {
                vol.Required(CONF_ACCESS_CODE): _ACCESS_CODE,
                # No default on the section key: the frontend would send that
                # default as the section's data and skip the defaults inside.
                vol.Required(CONF_ADVANCED): section(
                    _connection_schema({}), {"collapsed": not errors}
                ),
            }
        )
        if self._data:
            # What was typed comes back, except the code.
            connection = {k: self._data[k] for k in (CONF_HOST, CONF_VERIFY_SSL)}
            schema = self.add_suggested_values_to_schema(
                schema, {CONF_ADVANCED: connection}
            )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self._user_form({})
        advanced = dict(user_input.get(CONF_ADVANCED) or {})
        self._data = {
            CONF_HOST: str(advanced.get(CONF_HOST) or DEFAULT_HOST).strip(),
            CONF_ACCESS_CODE: user_input[CONF_ACCESS_CODE],
            CONF_VERIFY_SSL: bool(advanced.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)),
        }
        identity, errors = await self._async_try(self._data)
        if identity is not None:
            return await self._async_found(identity)
        if errors == {"base": "cannot_connect"}:
            return await self.async_step_unreachable()
        return self._user_form(errors)

    async def async_step_unreachable(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The gateway did not answer; say how to fix it and check again on Submit.

        The typed code is kept, so Submit alone retries.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data[CONF_HOST] = str(
                user_input.get(CONF_HOST) or DEFAULT_HOST
            ).strip()
            self._data[CONF_VERIFY_SSL] = bool(user_input.get(CONF_VERIFY_SSL))
            identity, errors = await self._async_try(self._data)
            if identity is not None:
                return await self._async_found(identity)
            if errors == {"base": "invalid_auth"}:
                return self._user_form(errors)
            if errors == {"base": "cannot_connect"}:
                errors = {"base": "still_cannot_connect"}
        return self.async_show_form(
            step_id="unreachable",
            data_schema=_connection_schema(self._data),
            description_placeholders={
                "host": self._data[CONF_HOST],
                "url": f"https://{self._data[CONF_HOST]}/",
                "default_host": DEFAULT_HOST,
            },
            errors=errors,
        )

    async def async_step_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The reboot schedule, off already, so Submit finishes the setup."""
        if user_input is not None:
            return self.async_create_entry(
                title=_title(self._data[CONF_HOST]),
                data=self._data,
                options=_schedule_options(user_input),
            )
        return self.async_show_form(
            step_id="schedule", data_schema=_schedule_schema({})
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address, access code or certificate check without re-adding.

        The gateway at the address must report the serial number (else MAC)
        the entry is keyed on; a different gateway aborts with another_gateway.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            # A blank access code keeps the stored one; the gateway never
            # accepts an empty code, so there is no ambiguity.
            data = dict(user_input)
            if not data.get(CONF_ACCESS_CODE):
                data[CONF_ACCESS_CODE] = entry.data[CONF_ACCESS_CODE]
            identity, errors = await self._async_try(data)
            if identity is not None:
                await self.async_set_unique_id(identity)
                self._abort_if_unique_id_mismatch(reason="another_gateway")
                # A title the user renamed is theirs; the default one names
                # the address and follows it.
                title = entry.title
                if title == _title(entry.data[CONF_HOST]):
                    title = _title(data[CONF_HOST])
                return self.async_update_reload_and_abort(entry, title=title, data=data)
        # The stored access code never goes back to the browser: a suggested
        # value is sent to the frontend, where a password field can reveal it.
        shown = {
            k: v for k, v in (user_input or entry.data).items() if k != CONF_ACCESS_CODE
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _reconfigure_schema(shown), shown
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_ACCESS_CODE: user_input[CONF_ACCESS_CODE]}
            _, errors = await self._async_try(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_ACCESS_CODE): _ACCESS_CODE}),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AttRouterOptionsFlow()


class AttRouterOptionsFlow(OptionsFlow):
    """The optional built-in reboot schedule."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=_schedule_options(user_input))
        return self.async_show_form(
            step_id="init", data_schema=_schedule_schema(self.config_entry.options)
        )
