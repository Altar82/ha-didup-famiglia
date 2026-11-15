"""Calendario compiti e promemoria."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DidupConfigEntry
from .entity import DidupEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: DidupConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(DidupCalendar(coordinator, uid) for uid in coordinator.data)


class DidupCalendar(DidupEntity, CalendarEntity):
    def __init__(self, coordinator, uid: str) -> None:
        super().__init__(coordinator, uid, "compiti")

    def _events(self) -> list[CalendarEvent]:
        st = self.student
        if not st:
            return []
        events: list[CalendarEvent] = []
        for h in st.data.homework:
            if not h.due:
                continue
            events.append(
                CalendarEvent(
                    start=h.due,
                    end=h.due + timedelta(days=1),
                    summary=f"{h.subject}: {h.text}" if h.subject else h.text,
                    description="\n".join(
                        x
                        for x in (
                            h.text,
                            f"Docente: {h.teacher}" if h.teacher else None,
                            f"Assegnato il {h.assigned.strftime('%d/%m/%Y')}" if h.assigned else None,
                        )
                        if x
                    ),
                    uid=f"{self._uid}_hw_{h.pk}",
                )
            )
        for r in st.data.reminders:
            if not r.date:
                continue
            events.append(
                CalendarEvent(
                    start=r.date,
                    end=r.date + timedelta(days=1),
                    summary=f"Promemoria: {r.text}",
                    description=f"Docente: {r.teacher}" if r.teacher else None,
                    uid=f"{self._uid}_pm_{r.pk}",
                )
            )
        events.sort(key=lambda e: e.start)
        return events

    @property
    def event(self) -> CalendarEvent | None:
        today = dt_util.now().date()
        for e in self._events():
            if e.start >= today:
                return e
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        s: date = dt_util.as_local(start_date).date()
        e: date = dt_util.as_local(end_date).date()
        return [ev for ev in self._events() if ev.end > s and ev.start <= e]
