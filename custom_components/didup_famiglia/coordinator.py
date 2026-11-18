"""DataUpdateCoordinator per DidUP Famiglia."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ArgoAuthError, ArgoClient, ArgoError, ArgoOutdatedClientError, Profile
from .const import (
    AUTH_SPID,
    CONF_AUTH_METHOD,
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
    EVENT_NEW_REMINDER,
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


def reauth_issue_id(entry_id: str) -> str:
    return f"reauth_{entry_id}"


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
        self.last_success: datetime | None = None
        self.last_error: str | None = None

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
            self.last_error = f"Accesso rifiutato: {err}"
            self._issue_reauth()
            raise ConfigEntryAuthFailed(str(err)) from err
        except ArgoOutdatedClientError as err:
            self.last_error = str(err)
            raise UpdateFailed(str(err)) from err
        except ArgoError as err:
            self.last_error = str(err)
            raise UpdateFailed(f"Errore comunicando con Argo: {err}") from err

        self.last_success = dt_util.utcnow()
        self.last_error = None
        ir.async_delete_issue(self.hass, DOMAIN, reauth_issue_id(self.config_entry.entry_id))
        await self._fire_new_items(result)
        return result

    def _issue_reauth(self) -> None:
        """Avviso in Riparazioni: Argo chiede un nuovo accesso (password cambiata o accesso SPID/CIE scaduto)."""
        entry = self.config_entry
        spid = entry.data.get(CONF_AUTH_METHOD) == AUTH_SPID
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            reauth_issue_id(entry.entry_id),
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="accesso_spid_scaduto" if spid else "accesso_non_valido",
            translation_placeholders={"account": entry.title},
            data={"entry_id": entry.entry_id},
        )

    def media_folder(self) -> str:
        """Cartella dei media di Home Assistant (visibile in Media → Media locali)."""
        base = self.hass.config.media_dirs.get("local") or self.hass.config.path("media")
        return os.path.join(base, DOMAIN)

    async def async_download_attachments(
        self, uid: str | None = None, notice_id: str | None = None, only_unread: bool = False
    ) -> list[str]:
        """Salva gli allegati nella cartella dei media; ritorna i percorsi relativi dei file nuovi."""
        saved: list[str] = []
        errors: list[str] = []
        base = self.media_folder()
        found = False
        for st_uid, st in (self.data or {}).items():
            if uid is not None and st_uid != uid:
                continue
            for n in st.data.notices:
                if notice_id is not None and n.pk != str(notice_id):
                    continue
                if notice_id is None and only_unread and not n.unread:
                    continue
                found = True
                folder = os.path.join(
                    base, _safe(st.name), _safe(f"{n.date.isoformat() if n.date else 'senza data'} - {n.title}")[:120]
                )
                for att_pk, name in n.files:
                    path = os.path.join(folder, _safe(name) or att_pk)
                    if await self.hass.async_add_executor_job(os.path.exists, path):
                        continue
                    try:
                        data = await self.client.async_download_attachment(st.profile, att_pk)
                    except ArgoError as err:
                        errors.append(f"{name}: {err}")
                        continue
                    await self.hass.async_add_executor_job(_write, path, data)
                    saved.append(os.path.relpath(path, os.path.dirname(base)))
        if notice_id is not None and not found:
            raise HomeAssistantError(f"Comunicazione {notice_id} non trovata")
        if errors and not saved:
            raise HomeAssistantError("Download non riuscito: " + "; ".join(errors))
        if errors:
            _LOGGER.warning("Alcuni allegati non sono stati scaricati: %s", "; ".join(errors))
        return saved

    async def async_confirm_notes(self, uid: str | None = None, note_id: str | None = None) -> int:
        """Presa visione delle note disciplinari: una (note_id) o tutte quelle non ancora viste."""
        done = 0
        errors: list[str] = []
        for st_uid, st in (self.data or {}).items():
            if uid is not None and st_uid != uid:
                continue
            for n in st.data.notes:
                if note_id is not None:
                    if n.pk != str(note_id):
                        continue
                elif n.seen:
                    continue
                try:
                    await self.client.async_confirm_note(st.profile, n.pk)
                    done += 1
                except ArgoError as err:
                    errors.append(f"nota del {n.date}: {err}")
        if note_id is not None and not done and not errors:
            raise HomeAssistantError(f"Nota {note_id} non trovata")
        if done:
            await self.async_request_refresh()
        if errors:
            raise HomeAssistantError("Presa visione non riuscita per " + "; ".join(errors))
        return done

    async def async_confirm_notices(self, uid: str | None = None, notice_id: str | None = None) -> int:
        """Presa visione: di una comunicazione (notice_id) o di tutte quelle in attesa.

        Ritorna quante comunicazioni sono state confermate.
        """
        done = 0
        errors: list[str] = []
        for st_uid, st in (self.data or {}).items():
            if uid is not None and st_uid != uid:
                continue
            for n in st.data.notices:
                if notice_id is not None:
                    if n.pk != str(notice_id):
                        continue
                elif not n.unread:
                    continue
                try:
                    await self.client.async_confirm_notice(
                        st.profile, n.pk, n.attachment_ids[0] if n.attachment_ids else None
                    )
                    done += 1
                except ArgoError as err:
                    errors.append(f"{n.title[:60]}: {err}")
        if notice_id is not None and not done and not errors:
            raise HomeAssistantError(f"Comunicazione {notice_id} non trovata")
        if done:
            await self.async_request_refresh()
        if errors:
            raise HomeAssistantError("Presa visione non riuscita per " + "; ".join(errors))
        return done

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
                EVENT_NEW_REMINDER: [(r.pk, r.as_dict()) for r in st.data.reminders],
            }
            for event, items in groups.items():
                known = set(seen.get(event, []))
                current = [pk for pk, _ in items]
                # gruppo appena aggiunto (aggiornamento dell'integrazione): niente raffica di eventi
                if not (first_run or new_student or event not in seen):
                    for pk, payload in items:
                        if pk not in known:
                            self.hass.bus.async_fire(
                                event,
                                {"alunno": st.name, "entry_id": self.config_entry.entry_id, **payload},
                            )
                if set(current) - known or event not in seen:
                    # teniamo anche i vecchi pk per non rinotificare elementi che spariscono e ricompaiono
                    seen[event] = list(dict.fromkeys([*current, *seen.get(event, [])]))[:2000]
                    changed = True
        if changed or first_run:
            await self._store.async_save(self._seen)


def _safe(name: str) -> str:
    """Nome di file/cartella senza caratteri problematici."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(name)).strip(" .")
    return re.sub(r"\s+\.", ".", re.sub(r"\s+", " ", name))


def _write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
