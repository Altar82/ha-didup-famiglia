"""Integrazione DidUP Famiglia (Argo) per Home Assistant."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import ATTR_ENTRY_ID, ATTR_NOTICE_ID, DOMAIN, SERVICE_ACK
from .coordinator import DidupCoordinator, reauth_issue_id

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.CALENDAR, Platform.BUTTON, Platform.BINARY_SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type DidupConfigEntry = ConfigEntry[DidupCoordinator]

ACK_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_NOTICE_ID): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def _presa_visione(call: ServiceCall) -> ServiceResponse:
        entry_id = call.data.get(ATTR_ENTRY_ID)
        notice_id = call.data.get(ATTR_NOTICE_ID)
        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED and (entry_id is None or e.entry_id == entry_id)
        ]
        if not entries:
            raise ServiceValidationError("Nessuna integrazione didUP Famiglia attiva corrisponde alla richiesta")
        done = 0
        for e in entries:
            coordinator: DidupCoordinator = e.runtime_data
            if notice_id is not None and not any(
                n.pk == str(notice_id) for st in (coordinator.data or {}).values() for n in st.data.notices
            ):
                continue
            done += await coordinator.async_confirm_notices(notice_id=notice_id)
        if notice_id is not None and not done:
            raise ServiceValidationError(f"Comunicazione {notice_id} non trovata")
        return {"confermate": done}

    hass.services.async_register(
        DOMAIN, SERVICE_ACK, _presa_visione, schema=ACK_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DidupConfigEntry) -> bool:
    coordinator = DidupCoordinator(hass, entry)
    entry.async_on_unload(coordinator.client.async_close)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: DidupConfigEntry) -> None:
    # il listener scatta anche quando salviamo il refresh token: ricarichiamo solo per le opzioni
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None or dict(entry.options) != coordinator.options_snapshot:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: DidupConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: DidupConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, reauth_issue_id(entry.entry_id))
