"""Config flow for AT&T Router Reboot."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .api import (
    AttRouterAuthError,
    AttRouterClient,
    AttRouterConnectionError,
    AttRouterError,
)
from .const import (
    CONF_ACCESS_CODE,
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


async def _validate(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Log in against the real gateway; raises on failure."""
    session = aiohttp.ClientSession()
    client = AttRouterClient(
        session,
        data[CONF_HOST],
        data[CONF_ACCESS_CODE],
        verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )
    try:
        await client.async_verify_access_code()
    finally:
        await session.close()


def _user_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, DEFAULT_HOST)): str,
            vol.Required(CONF_ACCESS_CODE): str,
            vol.Required(
                CONF_VERIFY_SSL,
                default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            ): bool,
        }
    )


class AttRouterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup, reconfigure and reauth for the gateway."""

    VERSION = 1

    async def _async_try(self, data: dict[str, Any]) -> dict[str, str]:
        try:
            await _validate(self.hass, data)
        except AttRouterAuthError:
            return {"base": "invalid_auth"}
        except AttRouterConnectionError:
            return {"base": "cannot_connect"}
        except AttRouterError:
            return {"base": "unknown"}
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()
            errors = await self._async_try(user_input)
            if not errors:
                return self.async_create_entry(
                    title=f"AT&T Gateway ({user_input[CONF_HOST]})",
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address or access code without re-adding the entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_try(user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_mismatch(reason="another_gateway")
                return self.async_update_reload_and_abort(entry, data=user_input)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _user_schema(entry.data), user_input or entry.data
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
            errors = await self._async_try(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_ACCESS_CODE): str}),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AttRouterOptionsFlow()


class AttRouterOptionsFlow(OptionsFlow):
    """The optional built-in reboot schedule."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            cleaned = dict(user_input)
            if cleaned.get(CONF_SCHEDULE) != SCHEDULE_WEEKLY:
                cleaned.pop(CONF_SCHEDULE_WEEKDAY, None)
            if cleaned.get(CONF_SCHEDULE) == SCHEDULE_OFF:
                cleaned.pop(CONF_SCHEDULE_TIME, None)
            return self.async_create_entry(data=cleaned)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCHEDULE,
                        default=options.get(CONF_SCHEDULE, DEFAULT_SCHEDULE),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=SCHEDULES,
                            translation_key="schedule",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_SCHEDULE_TIME,
                        default=options.get(CONF_SCHEDULE_TIME, DEFAULT_SCHEDULE_TIME),
                    ): selector.TimeSelector(),
                    vol.Optional(
                        CONF_SCHEDULE_WEEKDAY,
                        default=options.get(
                            CONF_SCHEDULE_WEEKDAY, DEFAULT_SCHEDULE_WEEKDAY
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=WEEKDAYS,
                            translation_key="weekday",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )
