"""Downloadable diagnostics."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import CONF_ACCESS_CODE
from .coordinator import AttRouterConfigEntry

# The access code is a credential; the host, serial and MAC identify the
# household's hardware, and the WAN address identifies the household itself.
REDACT = {CONF_ACCESS_CODE, CONF_HOST, "serial", "mac", "ipv4_address"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AttRouterConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    # asdict first: the redaction helper walks mappings, not dataclasses.
    data = asdict(coordinator.data) if coordinator.data is not None else None
    return {
        "config": async_redact_data(dict(entry.data), REDACT),
        "options": dict(entry.options),
        "data": async_redact_data(data, REDACT),
        "last_update_success": coordinator.last_update_success,
        "model_info": async_redact_data(coordinator.model_info, REDACT),
    }
