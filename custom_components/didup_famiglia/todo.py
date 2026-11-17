"""Lista "Circolari da confermare": spunta una comunicazione per confermarne la presa visione."""

from __future__ import annotations

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DidupConfigEntry
from .entity import DidupEntity

MAX_DONE = 10


async def async_setup_entry(
    hass: HomeAssistant, entry: DidupConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(DidupNoticeList(coordinator, uid) for uid in coordinator.data)


class DidupNoticeList(DidupEntity, TodoListEntity):
    """Da confermare in alto; le ultime confermate tra le completate."""

    _attr_icon = "mdi:clipboard-check-outline"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(self, coordinator, uid: str) -> None:
        super().__init__(coordinator, uid, "circolari_da_confermare")

    @property
    def todo_items(self) -> list[TodoItem] | None:
        st = self.student
        if not st:
            return None
        items: list[TodoItem] = []
        done = 0
        for n in st.data.notices:
            if not n.needs_ack:
                continue
            if n.acked:
                if done >= MAX_DONE:
                    continue
                done += 1
            parts = [x for x in (n.category, n.author) if x]
            if n.attachments:
                parts.append("Allegati: " + ", ".join(n.attachments))
            items.append(
                TodoItem(
                    uid=n.pk,
                    summary=n.title or "Comunicazione",
                    status=TodoItemStatus.COMPLETED if n.acked else TodoItemStatus.NEEDS_ACTION,
                    due=n.date,
                    description=" · ".join(parts) or None,
                )
            )
        return items

    async def async_update_todo_item(self, item: TodoItem) -> None:
        st = self.student
        notice = next((n for n in (st.data.notices if st else []) if n.pk == item.uid), None)
        if notice is None:
            raise HomeAssistantError("Comunicazione non trovata")
        if item.status != TodoItemStatus.COMPLETED:
            if notice.acked:
                raise HomeAssistantError("La presa visione su Argo non si può annullare")
            return
        if not notice.acked:
            await self.coordinator.async_confirm_notices(uid=self._uid, notice_id=notice.pk)
