"""Costanti per l'integrazione DidUP Famiglia."""

from __future__ import annotations

DOMAIN = "didup_famiglia"

CONF_SCHOOL_CODE = "school_code"
CONF_CLIENT_VERSION = "client_version"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_AUTH_METHOD = "auth_method"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_CALLBACK_URL = "callback_url"
AUTH_CREDENTIALS = "credentials"
AUTH_SPID = "spid"

# Versione dell'app ufficiale che Argo si aspetta nell'header argo-client-version.
# Se Argo risponde 410 va aggiornata (anche dalle opzioni dell'integrazione).
DEFAULT_CLIENT_VERSION = "1.30.2"
DEFAULT_SCAN_INTERVAL_MIN = 30
MIN_SCAN_INTERVAL_MIN = 10

# Eventi sul bus di Home Assistant per le automazioni
EVENT_NEW_GRADE = f"{DOMAIN}_nuovo_voto"
EVENT_NEW_NOTE = f"{DOMAIN}_nuova_nota"
EVENT_NEW_ABSENCE = f"{DOMAIN}_nuova_assenza"
EVENT_NEW_NOTICE = f"{DOMAIN}_nuova_comunicazione"
EVENT_NEW_HOMEWORK = f"{DOMAIN}_nuovo_compito"
EVENT_NEW_REMINDER = f"{DOMAIN}_nuovo_promemoria"

SERVICE_ACK = "presa_visione"
SERVICE_DOWNLOAD = "scarica_allegati"
SERVICE_ACK_NOTE = "presa_visione_nota"
ATTR_NOTE_ID = "nota"
ATTR_ONLY_UNREAD = "solo_da_confermare"
ATTR_NOTICE_ID = "comunicazione"
ATTR_ENTRY_ID = "config_entry_id"

STORAGE_VERSION = 1
