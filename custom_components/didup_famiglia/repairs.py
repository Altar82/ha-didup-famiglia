"""Riparazioni: nuovo accesso ad Argo."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult


class ReauthRepairFlow(RepairsFlow):
    """Porta al nuovo accesso: il form vero è quello di riautenticazione dell'integrazione."""

    def __init__(self, entry_id: str | None) -> None:
        self._entry_id = entry_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entry = self.hass.config_entries.async_get_entry(self._entry_id) if self._entry_id else None
        if user_input is not None:
            if entry is not None:
                entry.async_start_reauth(self.hass)
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"account": entry.title if entry else ""},
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    if issue_id.startswith("reauth_"):
        return ReauthRepairFlow(str((data or {}).get("entry_id") or issue_id.removeprefix("reauth_")))
    return ConfirmRepairFlow()
