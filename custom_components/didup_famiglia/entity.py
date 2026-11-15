"""Entità base: un dispositivo per ogni alunno."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DidupCoordinator, Student


class DidupEntity(CoordinatorEntity[DidupCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DidupCoordinator, uid: str, key: str) -> None:
        super().__init__(coordinator)
        self._uid = uid
        self._attr_unique_id = f"{uid}_{key}"
        self._attr_translation_key = key
        st = coordinator.data[uid]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uid)},
            name=st.name,
            manufacturer="Argo Software",
            model=" · ".join(x for x in (st.profile.class_name, st.profile.school_name) if x) or "didUP Famiglia",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def student(self) -> Student | None:
        return (self.coordinator.data or {}).get(self._uid)

    @property
    def available(self) -> bool:
        return super().available and self.student is not None
