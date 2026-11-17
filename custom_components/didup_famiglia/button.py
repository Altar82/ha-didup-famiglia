"""Pulsante di presa visione delle comunicazioni in bacheca."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DidupConfigEntry
from .entity import DidupEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: DidupConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(DidupAckButton(coordinator, uid) for uid in coordinator.data)


class DidupAckButton(DidupEntity, ButtonEntity):
    _attr_icon = "mdi:eye-check"

    def __init__(self, coordinator, uid: str) -> None:
        super().__init__(coordinator, uid, "presa_visione")

    async def async_press(self) -> None:
        """Conferma tutte le comunicazioni che chiedono la presa visione."""
        await self.coordinator.async_confirm_notices(uid=self._uid)
