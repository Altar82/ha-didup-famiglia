"""Integrazione DidUP Famiglia (Argo) per Home Assistant."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.typing import ConfigType

from .const import ATTR_ENTRY_ID, ATTR_NOTICE_ID, DOMAIN, SERVICE_ACK
from .coordinator import DidupCoordinator, reauth_issue_id

_LOGGER = logging.getLogger(__name__)

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
    _migra_identificativi(hass, entry, coordinator)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


def _migra_identificativi(hass: HomeAssistant, entry: DidupConfigEntry, coordinator: DidupCoordinator) -> None:
    """Riporta entità e dispositivi sull'id attuale dell'alunno.

    Le due API di Argo (vecchia /appfamiglia e nuova Famiglia) danno all'alunno identificativi diversi:
    senza questa migrazione, al cambio di API comparirebbero entità nuove e le vecchie resterebbero
    non disponibili (con automazioni, aree e storico legati a quelle vecchie).
    """
    attuali = {uid: st.name for uid, st in (coordinator.data or {}).items()}
    if not attuali:
        return
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        vecchio = next((i[1] for i in device.identifiers if i[0] == DOMAIN), None)
        if vecchio is None or vecchio in attuali:
            continue
        nuovo = next((u for u, n in attuali.items() if n and n == device.name), None)
        if nuovo is None and len(attuali) == 1:
            nuovo = next(iter(attuali))
        if nuovo is None:
            continue
        # un dispositivo già creato con l'id nuovo (prima della migrazione) è un doppione: via
        doppio = dev_reg.async_get_device(identifiers={(DOMAIN, nuovo)})
        if doppio is not None and doppio.id != device.id:
            for e in er.async_entries_for_device(ent_reg, doppio.id, include_disabled_entities=True):
                ent_reg.async_remove(e.entity_id)
            dev_reg.async_remove_device(doppio.id)
        for e in er.async_entries_for_device(ent_reg, device.id, include_disabled_entities=True):
            if not e.unique_id.startswith(f"{vecchio}_"):
                continue
            uid = nuovo + e.unique_id[len(vecchio):]
            if (altro := ent_reg.async_get_entity_id(e.domain, DOMAIN, uid)) and altro != e.entity_id:
                ent_reg.async_remove(altro)
            ent_reg.async_update_entity(e.entity_id, new_unique_id=uid)
        dev_reg.async_update_device(device.id, new_identifiers={(DOMAIN, nuovo)})
        _LOGGER.info("Identificativo dell'alunno %s aggiornato dopo il cambio di API di Argo", device.name)


async def _async_reload(hass: HomeAssistant, entry: DidupConfigEntry) -> None:
    # il listener scatta anche quando salviamo il refresh token: ricarichiamo solo per le opzioni
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None or dict(entry.options) != coordinator.options_snapshot:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: DidupConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: DidupConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, reauth_issue_id(entry.entry_id))
