"""Diagnostica: struttura della dashboard grezza, utile se Argo cambia i campi."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import DidupConfigEntry
from .const import CONF_CALLBACK_URL, CONF_REFRESH_TOKEN

TO_REDACT = {
    # credenziali e token (il refresh token SPID/CIE dà accesso all'account Argo)
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_REFRESH_TOKEN,
    CONF_CALLBACK_URL,
    "access_token",
    "token",
    "x-auth-token",
    # nomi di docenti, autori e alunni
    "docente",
    "desDocente",
    "autore",
    "alunno",
    # testi liberi che possono contenere nomi o dati personali
    "desNota",
    "desMessaggio",
    "desCommento",
    "desAnnotazioni",
    "nomeFile",
    "desFile",
    "desDescrizione",
    "nota",
    "descrizione",
    "commentoGiustificazione",
    "desNome",
    "desCognome",
    # anagrafica
    "nominativo",
    "nome",
    "cognome",
    "desEmail",
    "codFiscale",
    "desCf",
    "email",
}


def _shape(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, list):
            out[k] = {"count": len(v), "sample": v[0] if v else None}
        elif isinstance(v, dict):
            out[k] = {"keys": sorted(v)}
        else:
            out[k] = v
    return out


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: DidupConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "students": {
            uid[-6:]: async_redact_data(
                {
                    "profile_raw": st.profile.raw,
                    "dashboard": _shape(st.raw),
                    "parsed_counts": {
                        "voti": len(st.data.grades),
                        "compiti": len(st.data.homework),
                        "promemoria": len(st.data.reminders),
                        "appello": len(st.data.absences),
                        "note": len(st.data.notes),
                        "bacheca": len(st.data.notices),
                    },
                },
                TO_REDACT,
            )
            for uid, st in (coordinator.data or {}).items()
        },
    }
