"""Downloadable diagnostics."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import CONF_ACCESS_CODE
from .coordinator import AttRouterConfigEntry

# The access code is a credential; the host, serial and MAC identify the
# household's hardware.
REDACT = {CONF_ACCESS_CODE, CONF_HOST, "serial", "mac"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AttRouterConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "config": async_redact_data(dict(entry.data), REDACT),
        "options": dict(entry.options),
        "data": coordinator.data,
        "last_update_success": coordinator.last_update_success,
        "model_info": async_redact_data(coordinator.model_info, REDACT),
    }
