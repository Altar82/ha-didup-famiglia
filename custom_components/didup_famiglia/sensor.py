"""Sensori DidUP Famiglia."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DidupConfigEntry
from .coordinator import Student
from .entity import DidupEntity

MAX_ATTR_ITEMS = 10


def _today():
    return dt_util.now().date()


def _homework_on(st: Student, day) -> list[dict[str, Any]]:
    return [h.as_dict() for h in st.data.homework if h.due == day]


def _upcoming(st: Student, days: int) -> list[dict[str, Any]]:
    t = _today()
    return [h.as_dict() for h in st.data.homework if h.due and t < h.due <= t + timedelta(days=days)]


def _last_grade(st: Student):
    """Ultimo voto con valore numerico (esclude Impreparato, Comunicazione, ecc.)."""
    return next((g for g in st.data.grades if g.value is not None), None)


def _last_notice(st: Student):
    """Ultima comunicazione pubblicata in bacheca (la più recente per data)."""
    return st.data.notices[0] if st.data.notices else None


@dataclass(frozen=True, kw_only=True)
class DidupSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Student], Any]
    attrs_fn: Callable[[Student], dict[str, Any]] | None = None


SENSORS: tuple[DidupSensorDescription, ...] = (
    DidupSensorDescription(
        key="media_generale",
        icon="mdi:chart-line",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda st: st.data.average,
        attrs_fn=lambda st: {"medie_materie": st.data.subject_averages},
    ),
    DidupSensorDescription(
        key="ultimo_voto",
        icon="mdi:numeric",
        value_fn=lambda st: (g.display if (g := _last_grade(st)) else None),
        attrs_fn=lambda st: {
            **(g.as_dict() if (g := _last_grade(st)) else {}),
            "ultimi_voti": [g.as_dict() for g in st.data.grades if g.value is not None][:MAX_ATTR_ITEMS],
            # giudizi senza valore registrati come voti (Impreparato, Comunicazione...)
            "annotazioni": [g.as_dict() for g in st.data.grades if g.value is None][:MAX_ATTR_ITEMS],
        },
    ),
    DidupSensorDescription(
        key="numero_voti",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda st: sum(1 for g in st.data.grades if g.value is not None),
    ),
    DidupSensorDescription(
        key="compiti_domani",
        icon="mdi:book-clock",
        value_fn=lambda st: len(_homework_on(st, _today() + timedelta(days=1))),
        attrs_fn=lambda st: {"compiti": _homework_on(st, _today() + timedelta(days=1))},
    ),
    DidupSensorDescription(
        key="compiti_settimana",
        icon="mdi:book-multiple",
        value_fn=lambda st: len(_upcoming(st, 7)),
        attrs_fn=lambda st: {"compiti": _upcoming(st, 7)},
    ),
    DidupSensorDescription(
        key="assenze",
        icon="mdi:account-off",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda st: sum(1 for a in st.data.absences if a.kind == "assenza"),
        attrs_fn=lambda st: {
            "ritardi": sum(1 for a in st.data.absences if a.kind == "ritardo"),
            "uscite_anticipate": sum(1 for a in st.data.absences if a.kind == "uscita"),
            "ultimi_eventi": [a.as_dict() for a in st.data.absences[:MAX_ATTR_ITEMS]],
        },
    ),
    DidupSensorDescription(
        key="da_giustificare",
        icon="mdi:file-sign",
        value_fn=lambda st: sum(1 for a in st.data.absences if a.to_justify),
        attrs_fn=lambda st: {"eventi": [a.as_dict() for a in st.data.absences if a.to_justify]},
    ),
    DidupSensorDescription(
        key="note_disciplinari",
        icon="mdi:alert-octagon",
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda st: len(st.data.notes),
        attrs_fn=lambda st: {"ultime_note": [n.as_dict() for n in st.data.notes[:MAX_ATTR_ITEMS]]},
    ),
    DidupSensorDescription(
        key="ultima_comunicazione",
        icon="mdi:bullhorn",
        value_fn=lambda st: (n.title[:255] or None) if (n := _last_notice(st)) else None,
        attrs_fn=lambda st: n.as_dict() if (n := _last_notice(st)) else {},
    ),
    DidupSensorDescription(
        key="comunicazioni_da_leggere",
        icon="mdi:bulletin-board",
        value_fn=lambda st: sum(1 for n in st.data.notices if n.unread),
        attrs_fn=lambda st: {
            "da_leggere": [n.as_dict() for n in st.data.notices if n.unread][:MAX_ATTR_ITEMS],
            "ultime_comunicazioni": [n.as_dict() for n in st.data.notices[:MAX_ATTR_ITEMS]],
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: DidupConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        DidupSensor(coordinator, uid, desc) for uid in coordinator.data for desc in SENSORS
    )


class DidupSensor(DidupEntity, SensorEntity):
    entity_description: DidupSensorDescription

    def __init__(self, coordinator, uid: str, description: DidupSensorDescription) -> None:
        super().__init__(coordinator, uid, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        st = self.student
        return self.entity_description.value_fn(st) if st else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        st = self.student
        if not st or not self.entity_description.attrs_fn:
            return None
        return self.entity_description.attrs_fn(st)
