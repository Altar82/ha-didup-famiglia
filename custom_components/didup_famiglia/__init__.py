"""Integrazione DidUP Famiglia (Argo) per Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import DidupCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.CALENDAR]

type DidupConfigEntry = ConfigEntry[DidupCoordinator]


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
