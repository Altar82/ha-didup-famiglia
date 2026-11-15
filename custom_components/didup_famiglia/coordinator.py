"""DataUpdateCoordinator per DidUP Famiglia."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ArgoAuthError, ArgoClient, ArgoError, ArgoOutdatedClientError, Profile
from .const import (
    CONF_CLIENT_VERSION,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SCHOOL_CODE,
    DEFAULT_CLIENT_VERSION,
    DEFAULT_SCAN_INTERVAL_MIN,
    DOMAIN,
    EVENT_NEW_ABSENCE,
    EVENT_NEW_GRADE,
    EVENT_NEW_HOMEWORK,
    EVENT_NEW_NOTE,
    EVENT_NEW_NOTICE,
    STORAGE_VERSION,
)
from .parse import StudentData, parse_dashboard

_LOGGER = logging.getLogger(__name__)


@dataclass
class Student:
    profile: Profile
    data: StudentData
    raw: dict[str, Any]

    @property
    def name(self) -> str:
        return self.profile.name or f"Alunno {self.profile.unique_id[-4:]}"


def make_client(
    hass: HomeAssistant,
    data: dict[str, Any],
    options: dict[str, Any] | None = None,
    on_refresh_token: Callable[[str], None] | None = None,
) -> ArgoClient:
    # Sessione dedicata con cookie jar proprio (il login SSO usa i cookie)
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    return ArgoClient(
        session,
        (options or {}).get(CONF_CLIENT_VERSION, DEFAULT_CLIENT_VERSION),
        school_code=data.get(CONF_SCHOOL_CODE, ""),
        username=data.get(CONF_USERNAME),
        password=data.get(CONF_PASSWORD),
        refresh_token=data.get(CONF_REFRESH_TOKEN),
        on_refresh_token=on_refresh_token,
    )


class DidupCoordinator(DataUpdateCoordinator[dict[str, Student]]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MIN)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(minutes=minutes),
        )
        # opzioni con cui è partita l'entry: il listener ricarica solo se cambiano
        self.options_snapshot = dict(entry.options)
        self.client = make_client(hass, dict(entry.data), dict(entry.options), self._save_refresh_token)
        self._store: Store[dict[str, dict[str, list[str]]]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.seen"
        )
        self._seen: dict[str, dict[str, list[str]]] | None = None

    def _save_refresh_token(self, token: str) -> None:
        """SPID/CIE: Argo ruota il refresh token, va salvato a ogni rinnovo."""
        if self.config_entry.data.get(CONF_REFRESH_TOKEN) != token:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, CONF_REFRESH_TOKEN: token}
            )

    async def _async_update_data(self) -> dict[str, Student]:
        try:
            if not self.client.profiles:
                await self.client.async_login()
            result: dict[str, Student] = {}
            for profile in list(self.client.profiles):
                raw = await self.client.async_get_dashboard(profile)
                result[profile.unique_id] = Student(profile, parse_dashboard(raw), raw)
        except ArgoAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ArgoOutdatedClientError as err:
            raise UpdateFailed(str(err)) from err
        except ArgoError as err:
            raise UpdateFailed(f"Errore comunicando con Argo: {err}") from err

        await self._fire_new_items(result)
        return result

    async def _fire_new_items(self, students: dict[str, Student]) -> None:
        first_run = False
        if self._seen is None:
            self._seen = await self._store.async_load()
            if self._seen is None:
                self._seen, first_run = {}, True

        changed = False
        for uid, st in students.items():
            seen = self._seen.setdefault(uid, {})
            new_student = not seen
            groups = {
                EVENT_NEW_GRADE: [(g.pk, g.as_dict()) for g in st.data.grades],
                EVENT_NEW_NOTE: [(n.pk, n.as_dict()) for n in st.data.notes],
                EVENT_NEW_ABSENCE: [(a.pk, a.as_dict()) for a in st.data.absences],
                EVENT_NEW_NOTICE: [(n.pk, n.as_dict()) for n in st.data.notices],
                EVENT_NEW_HOMEWORK: [(h.pk, h.as_dict()) for h in st.data.homework],
            }
            for event, items in groups.items():
                known = set(seen.get(event, []))
                current = [pk for pk, _ in items]
                if not (first_run or new_student):
                    for pk, payload in items:
                        if pk not in known:
                            self.hass.bus.async_fire(
                                event,
                                {"alunno": st.name, "entry_id": self.config_entry.entry_id, **payload},
                            )
                if set(current) - known:
                    # teniamo anche i vecchi pk per non rinotificare elementi che spariscono e ricompaiono
                    seen[event] = list(dict.fromkeys([*current, *seen.get(event, [])]))[:2000]
                    changed = True
        if changed or first_run:
            await self._store.async_save(self._seen)
