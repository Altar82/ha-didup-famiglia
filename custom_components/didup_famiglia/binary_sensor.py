"""Stato del collegamento con Argo."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DidupConfigEntry
from .entity import DidupEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: DidupConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(DidupConnection(coordinator, uid) for uid in coordinator.data)


class DidupConnection(DidupEntity, BinarySensorEntity):
    """Acceso se l'ultimo aggiornamento da Argo è riuscito. Resta disponibile anche quando Argo non risponde."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, uid: str) -> None:
        super().__init__(coordinator, uid, "collegamento_argo")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator
        return {
            "ultimo_aggiornamento_riuscito": c.last_success.isoformat() if c.last_success else None,
            "errore": c.last_error,
        }
