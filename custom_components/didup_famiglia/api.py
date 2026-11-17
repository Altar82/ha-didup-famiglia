"""Client asincrono (non ufficiale) per le API dell'app didUP Famiglia di Argo.

Le API non sono pubbliche: questo client riproduce il flusso dell'app ufficiale
(OAuth2 + PKCE su auth.portaleargo.it, poi /appfamiglia/api/rest/).
Il modulo non dipende da Home Assistant, così si può provare anche da riga di
comando (vedi tools/prova_login.py).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

AUTH_URL = "https://auth.portaleargo.it/oauth2/auth"
TOKEN_URL = "https://auth.portaleargo.it/oauth2/token"
SSO_LOGIN_URL = "https://www.portaleargo.it/auth/sso/login"
API_BASE = "https://www.portaleargo.it/appfamiglia/api/rest/"
# API "Famiglia" della web app: serve per le operazioni di scrittura (presa visione)
FAMIGLIA_BASE = "https://didattica.portaleargo.it/famiglia/api/"
FAMIGLIA_VERSION = "4.1.0"
CLIENT_ID = "72fd6dea-d0ab-4bb9-8eaa-3ac24c84886c"
REDIRECT_URI = "it.argosoft.didup.famiglia.new://login-callback"
SCOPES = "openid offline profile user.roles argo"
USER_AGENT = "okhttp/4.12.0"

MAX_HOPS = 12
TIMEOUT = aiohttp.ClientTimeout(total=30)
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=120)
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


class ArgoError(Exception):
    """Errore generico."""


class ArgoAuthError(ArgoError):
    """Credenziali errate o login rifiutato."""


class ArgoConnectionError(ArgoError):
    """Problema di rete o risposta inattesa."""


class ArgoOutdatedClientError(ArgoError):
    """Argo rifiuta la versione dichiarata dell'app (HTTP 410)."""


@dataclass
class Profile:
    """Un profilo alunno restituito dal login (uno per figlio)."""

    token: str
    cod_min: str
    options: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    name: str | None = None
    class_name: str | None = None
    school_name: str | None = None
    student_id: str | None = None
    scheda_pk: str | None = None
    year_start: str | None = None

    @property
    def unique_id(self) -> str:
        return self.student_id or f"{self.cod_min}_{self.token[:8]}"


# ---------------------------------------------------------------------------
# Parsing HTML del flusso SSO (logica pura, testabile offline)
# ---------------------------------------------------------------------------


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.forms: list[dict[str, Any]] = []
        self.meta_refresh: list[str] = []
        self.has_password = False
        self._form: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "form":
            self._form = {
                "action": a.get("action", ""),
                "method": a.get("method", "get").lower(),
                "inputs": {},
            }
            self.forms.append(self._form)
        elif tag in ("input", "button") and self._form is not None:
            name = a.get("name")
            if a.get("type", "").lower() == "password":
                self.has_password = True
            if name and (tag == "input" or a.get("value")):
                if a.get("type", "").lower() in ("checkbox", "radio") and "checked" not in a:
                    return
                self._form["inputs"].setdefault(name, a.get("value", ""))
        elif tag == "input" and a.get("type", "").lower() == "password":
            self.has_password = True
        elif tag == "meta" and a.get("http-equiv", "").lower() == "refresh":
            content = a.get("content", "")
            if "url=" in content.lower():
                self.meta_refresh.append(content[content.lower().index("url=") + 4 :].strip("'\" "))

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._form = None


def _is_oauth_continuation(url: str, state: str) -> bool:
    """True se url è un passo legittimo del flusso OAuth di Argo per questo login."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme != "https" or p.hostname != "auth.portaleargo.it" or p.path != "/oauth2/auth":
        return False
    q = parse_qs(p.query)
    if not ({"consent_verifier", "login_verifier"} & q.keys()):
        return False
    if q.get("client_id", [CLIENT_ID])[0] != CLIENT_ID:
        return False
    if "state" in q and q["state"][0] != state:
        return False
    if "redirect_uri" in q and q["redirect_uri"][0] != REDIRECT_URI:
        return False
    return True


def find_continuation(html: str, base_url: str, state: str) -> tuple[str, str, dict[str, str]] | None:
    """Cerca nella pagina il passo successivo del flusso.

    Ritorna (metodo, url, dati_form) oppure None.
    Argo da fine ottobre 2026 risponde al POST del login con HTTP 200 e una
    pagina che contiene il link di prosecuzione verso /oauth2/auth?consent_verifier=...
    """
    parser = _PageParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - HTML malformato: proviamo comunque le regex
        pass

    candidates = [urljoin(base_url, unescape(h)) for h in parser.links + parser.meta_refresh]
    # anche eventuali redirect via JavaScript
    for m in re.finditer(r"""https://auth\.portaleargo\.it/oauth2/auth\?[^"'\s<>]+""", html):
        candidates.append(unescape(m.group(0)).replace("\\u0026", "&").replace("\\/", "/"))

    for url in candidates:
        if _is_oauth_continuation(url, state):
            return ("get", url, {})

    # Pagina di consenso con form (fallback): la inviamo solo se punta a portaleargo
    for form in parser.forms:
        action = urljoin(base_url, unescape(form["action"] or base_url))
        host = urlparse(action).hostname or ""
        if not host.endswith("portaleargo.it"):
            continue
        if "/consent" in action or "consent_challenge" in form["inputs"]:
            return (form["method"], action, dict(form["inputs"]))
    return None


def page_looks_like_login(html: str) -> bool:
    parser = _PageParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        return False
    return parser.has_password


def extract_code(location: str, state: str) -> str:
    p = urlparse(location)
    expected = urlparse(REDIRECT_URI)
    if (p.scheme, p.netloc, p.path) != (expected.scheme, expected.netloc, expected.path):
        raise ArgoConnectionError("Callback OAuth inattesa")
    q = parse_qs(p.query)
    if "error" in q:
        raise ArgoAuthError(q.get("error_description", q["error"])[0])
    if q.get("state", [None])[0] != state:
        raise ArgoConnectionError("State OAuth non valido")
    code = q.get("code", [None])[0]
    if not code:
        raise ArgoConnectionError("Codice OAuth mancante")
    return code


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)[:64]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _authorize_params() -> tuple[dict[str, str], str, str]:
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": CLIENT_ID,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "nonce": secrets.token_urlsafe(24),
        "prompt": "login",
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    return params, verifier, state


def build_authorize_url() -> tuple[str, str, str]:
    """URL da aprire nel browser per il login manuale (SPID/CIE).

    Ritorna (url, code_verifier, state): verifier e state servono poi per
    validare l'indirizzo di ritorno incollato dall'utente.
    """
    params, verifier, state = _authorize_params()
    return f"{AUTH_URL}?{urlencode(params)}", verifier, state


def parse_callback(text: str, state: str) -> str:
    """Estrae il codice OAuth da quello che l'utente incolla.

    Accetta l'indirizzo completo it.argosoft.didup.famiglia.new://login-callback?code=...,
    solo la parte dopo il '?' oppure il solo codice.
    """
    text = (text or "").strip().strip("'\"")
    if "://" in text:
        return extract_code(text, state)
    query = text.split("?", 1)[-1]
    q = parse_qs(query)
    if "code" in q:
        if "error" in q:
            raise ArgoAuthError(q.get("error_description", q["error"])[0])
        if "state" in q and q["state"][0] != state:
            raise ArgoConnectionError("State OAuth non valido: rigenera il link e riprova")
        return q["code"][0]
    if re.fullmatch(r"[A-Za-z0-9._~\-]{20,}", text):
        return text
    raise ArgoConnectionError("Indirizzo di ritorno non riconosciuto")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ArgoClient:
    """Client per un account genitore (può avere più figli/profili)."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_version: str,
        *,
        school_code: str = "",
        username: str | None = None,
        password: str | None = None,
        refresh_token: str | None = None,
        on_refresh_token: Callable[[str], None] | None = None,
    ) -> None:
        """Due modalità.

        - credenziali Argo: school_code + username + password, login automatico;
        - SPID/CIE: solo refresh_token (ottenuto con il login nel browser), che
          viene rinnovato a ogni refresh e passato a on_refresh_token per salvarlo.
        """
        # La sessione DEVE avere un cookie jar suo: il flusso SSO usa i cookie.
        self._session = session
        self.school_code = (school_code or "").strip().upper()
        self.username = (username or "").strip()
        self._password = password
        self.client_version = client_version
        self._access_token: str | None = None
        self._refresh_token: str | None = refresh_token
        self._on_refresh_token = on_refresh_token
        self._expires_at = 0.0
        self.profiles: list[Profile] = []
        # sessioni dell'API Famiglia, per cod_min: lista di (token, cod_min) nell'ordine di Argo
        self._famiglia: list[dict[str, Any]] | None = None
        self._legacy = False  # True se Argo risponde solo con la vecchia API /appfamiglia

    @property
    def uses_credentials(self) -> bool:
        return bool(self._password)

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    async def async_close(self) -> None:
        """Dimentica i token. La sessione è di Home Assistant: la chiude lui."""
        self._access_token = None
        self._famiglia = None
        self._session.cookie_jar.clear()

    # ------------------------------------------------------------- OAuth
    async def _get(self, url: str, **kw: Any) -> tuple[int, str | None, str, str]:
        async with self._session.get(
            url, allow_redirects=False, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, **kw
        ) as r:
            return r.status, r.headers.get("Location"), await r.text(errors="replace"), str(r.url)

    async def _post_form(self, url: str, data: dict[str, str]) -> tuple[int, str | None, str, str]:
        async with self._session.post(
            url,
            data=data,
            allow_redirects=False,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as r:
            return r.status, r.headers.get("Location"), await r.text(errors="replace"), str(r.url)

    async def _authorize(self) -> tuple[str, str]:
        """Esegue login SSO e ritorna (code, code_verifier)."""
        params, verifier, state = _authorize_params()
        try:
            self._session.cookie_jar.clear()
            status, loc, _, url = await self._get(AUTH_URL, params=params)
            if status not in (301, 302, 303, 307) or not loc:
                raise ArgoConnectionError(f"Authorize: HTTP {status}")
            login_url = urljoin(url, loc)
            challenge_id = parse_qs(urlparse(login_url).query).get("login_challenge", [None])[0]
            if not challenge_id:
                raise ArgoConnectionError("login_challenge mancante")
            # carica la pagina per ottenere eventuali cookie
            await self._get(login_url)

            status, loc, body, url = await self._post_form(
                SSO_LOGIN_URL,
                {
                    "challenge": challenge_id,
                    "client_id": CLIENT_ID,
                    "prefill": "true",
                    "famiglia_customer_code": self.school_code,
                    "username": self.username,
                    "password": self._password,
                    "login": "true",
                },
            )

            for hop in range(MAX_HOPS):
                if status in (301, 302, 303, 307, 308) and loc:
                    if loc.startswith(REDIRECT_URI.split("://")[0] + "://"):
                        return extract_code(loc, state), verifier
                    nxt = urljoin(url, loc)
                    if not (urlparse(nxt).hostname or "").endswith("portaleargo.it"):
                        raise ArgoConnectionError(f"Redirect inatteso verso {urlparse(nxt).hostname}")
                    status, loc, body, url = await self._get(nxt)
                    continue
                if status == 200:
                    cont = find_continuation(body, url, state)
                    if cont is None:
                        if page_looks_like_login(body):
                            raise ArgoAuthError("Credenziali rifiutate da Argo")
                        _LOGGER.debug("Pagina SSO non riconosciuta (hop %s, %s): %s", hop, url, body[:500])
                        raise ArgoConnectionError("Pagina SSO inattesa: il flusso di login di Argo è cambiato")
                    method, nxt, data = cont
                    if method == "post":
                        status, loc, body, url = await self._post_form(nxt, data)
                    else:
                        status, loc, body, url = await self._get(nxt)
                    continue
                if status in (400, 401, 403):
                    raise ArgoAuthError(f"Login rifiutato (HTTP {status})")
                raise ArgoConnectionError(f"Login: HTTP {status} su {url}")
            raise ArgoConnectionError("Troppi redirect durante il login")
        except aiohttp.ClientError as err:
            raise ArgoConnectionError(str(err)) from err

    async def _token_request(self, data: dict[str, str]) -> None:
        try:
            async with self._session.post(
                TOKEN_URL, data=data, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
            ) as r:
                if r.status in (400, 401):
                    raise ArgoAuthError(f"Token rifiutato (HTTP {r.status})")
                if r.status != 200:
                    raise ArgoConnectionError(f"Token: HTTP {r.status}")
                tok = await r.json(content_type=None)
        except aiohttp.ClientError as err:
            raise ArgoConnectionError(str(err)) from err
        old_refresh = self._refresh_token
        self._access_token = tok["access_token"]
        self._refresh_token = tok.get("refresh_token", self._refresh_token)
        self._expires_at = time.time() + int(tok.get("expires_in", 3600)) - 60
        if self._on_refresh_token and self._refresh_token and self._refresh_token != old_refresh:
            self._on_refresh_token(self._refresh_token)

    async def _app_login(self) -> None:
        """Sessioni applicative (una per figlio).

        Prima l'API Famiglia usata dall'app attuale; se non risponde si prova la vecchia API
        /appfamiglia, che Argo sta dismettendo (da novembre 2026 risponde 503).
        """
        self._legacy = False
        try:
            data = await self._api("login", body={}, profile=None, _retry=False)
        except ArgoConnectionError as err:
            _LOGGER.debug("Login API Famiglia non riuscito (%s), provo l'API precedente", err)
            self._legacy = True
            body = {
                "lista-opzioni-notifiche": "{}",
                "lista-x-auth-token": "[]",
                "clientID": secrets.token_urlsafe(57),
            }
            try:
                data = await self._api("login", body=body, profile=None, _retry=False)
            except ArgoConnectionError:
                self._legacy = False
                raise err from None
        items = data.get("data") or []
        if isinstance(items, dict):
            items = [items]
        profiles: list[Profile] = []
        for it in items:
            if not it.get("token"):
                continue
            opts = it.get("opzioni") or []
            if isinstance(opts, list):
                opts = {o.get("chiave"): o.get("valore") for o in opts if isinstance(o, dict)}
            profiles.append(Profile(token=it["token"], cod_min=str(it.get("codMin", "")), options=opts, raw=it))
        if not profiles:
            raise ArgoAuthError("Nessun profilo alunno associato all'account")
        for n, p in enumerate(profiles):
            await self._load_profile_info(p)
            if not p.student_id:
                # fallback stabile tra un login e l'altro (il token cambia)
                p.student_id = f"{self.school_code or p.cod_min}_{p.cod_min}_{n}"
        self.profiles = profiles

    async def _load_profile_info(self, p: Profile) -> None:
        try:
            data = (await self._api("profilo", profile=p, method="GET", _retry=False)).get("data") or {}
        except ArgoError as err:
            _LOGGER.debug("profilo non disponibile: %s", err)
            data = {}
        alunno = data.get("alunno") or {}
        scheda = data.get("scheda") or {}
        classe = scheda.get("classe") or {}
        scuola = scheda.get("scuola") or {}
        anno = data.get("anno") or {}
        p.year_start = anno.get("dataInizio")
        p.name = (
            alunno.get("nominativo")
            or " ".join(x for x in (alunno.get("nome"), alunno.get("cognome")) if x)
            or p.raw.get("nominativo")
            or None
        )
        p.class_name = " ".join(x for x in (classe.get("desDenominazione"), classe.get("desSezione")) if x) or None
        p.school_name = scuola.get("desDenominazione") or scuola.get("descrizione")
        p.scheda_pk = str(scheda["pk"]) if scheda.get("pk") else None
        # stesso identificativo con entrambe le API (alunnoPK nella nuova), così le entità non cambiano
        pk = alunno.get("pk") or alunno.get("alunnoPK") or scheda.get("pk")
        p.student_id = f"{self.school_code or p.cod_min}_{pk}" if pk else None

    async def _exchange_code(self, code: str, verifier: str) -> None:
        await self._token_request(
            {
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
                "client_id": CLIENT_ID,
            }
        )

    async def _refresh(self) -> None:
        if not self._refresh_token:
            raise ArgoAuthError("Nessun refresh token: serve un nuovo accesso")
        await self._token_request(
            {"refresh_token": self._refresh_token, "grant_type": "refresh_token", "client_id": CLIENT_ID}
        )

    async def async_login(self) -> list[Profile]:
        """Login completo e caricamento dei profili.

        Con le credenziali Argo rifà il login SSO; in modalità SPID/CIE usa il
        refresh token salvato (se è scaduto serve un nuovo accesso dal browser).
        """
        if self.uses_credentials:
            code, verifier = await self._authorize()
            await self._exchange_code(code, verifier)
        else:
            await self._refresh()
        await self._app_login()
        return self.profiles

    async def async_login_with_callback(self, callback: str, verifier: str, state: str) -> list[Profile]:
        """Completa un login fatto nel browser (SPID/CIE) con l'indirizzo di ritorno incollato."""
        code = parse_callback(callback, state)
        await self._exchange_code(code, verifier)
        await self._app_login()
        return self.profiles

    async def _ensure_token(self) -> None:
        if self._access_token and time.time() < self._expires_at:
            return
        if self._refresh_token:
            try:
                await self._refresh()
                return
            except ArgoAuthError:
                if not self.uses_credentials:
                    raise
                _LOGGER.debug("Refresh token scaduto, rifaccio il login")
        await self.async_login()

    # ------------------------------------------------------------- REST
    async def _api(
        self,
        path: str,
        *,
        profile: Profile | None,
        body: dict[str, Any] | None = None,
        method: str = "POST",
        _retry: bool = True,
    ) -> dict[str, Any]:
        legacy = self._legacy
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "argo-client-version": self.client_version if legacy else FAMIGLIA_VERSION,
            "Authorization": f"Bearer {self._access_token}",
        }
        if legacy:
            headers["User-Agent"] = USER_AGENT
        else:
            headers["os-type"] = "WEB"
        if profile is not None:
            headers["x-auth-token"] = profile.token
            headers["x-cod-min"] = profile.cod_min
        try:
            async with self._session.request(
                method,
                (API_BASE if legacy else FAMIGLIA_BASE) + path,
                headers=headers,
                data=json.dumps(body) if body is not None else None,
                timeout=TIMEOUT,
            ) as r:
                if r.status == 410:
                    raise ArgoOutdatedClientError(
                        f"Argo rifiuta la versione app {self.client_version}: aggiornala nelle opzioni"
                    )
                if r.status in (401, 403) and _retry:
                    self._expires_at = 0
                    await self._ensure_token()
                    if profile is not None:
                        # anche il token del profilo può essere scaduto: rifacciamo il login applicativo
                        await self._app_login()
                        profile = next((p for p in self.profiles if p.unique_id == profile.unique_id), None)
                        if profile is None:
                            raise ArgoAuthError("Profilo alunno non più disponibile")
                    return await self._api(path, profile=profile, body=body, method=method, _retry=False)
                if r.status in (401, 403):
                    raise ArgoAuthError(f"{path}: HTTP {r.status}")
                if r.status != 200:
                    raise ArgoConnectionError(f"{path}: HTTP {r.status}")
                data = await r.json(content_type=None)
        except aiohttp.ClientError as err:
            raise ArgoConnectionError(str(err)) from err
        if isinstance(data, dict) and data.get("success") is False:
            raise ArgoConnectionError(f"{path}: {data.get('msg') or data.get('message') or 'errore'}")
        return data if isinstance(data, dict) else {"data": data}

    async def async_get_dashboard(self, profile: Profile) -> dict[str, Any]:
        """Scarica la dashboard completa di un profilo."""
        await self._ensure_token()
        profile = next((p for p in self.profiles if p.unique_id == profile.unique_id), profile)
        since = "2000-01-01 00:00:00.000"
        if not self._legacy and profile.year_start:
            # l'API Famiglia vuole l'inizio dell'anno scolastico (dati completi dell'anno)
            since = f"{str(profile.year_start)[:10]} 00:00:00.000"
        body = {
            "dataultimoaggiornamento": since,
            "opzioni": json.dumps(profile.options),
        }
        data = await self._api("dashboard/dashboard", profile=profile, body=body)
        payload = data.get("data", data)
        if isinstance(payload, dict) and isinstance(payload.get("dati"), list):
            return payload["dati"][0] if payload["dati"] else {}
        if isinstance(payload, list):
            return payload[0] if payload else {}
        return payload if isinstance(payload, dict) else {}

    # ------------------------------------------------------- API Famiglia
    async def _famiglia_api(
        self, path: str, body: dict[str, Any], session: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "argo-client-version": FAMIGLIA_VERSION,
            "os-type": "WEB",
            "Authorization": f"Bearer {self._access_token}",
        }
        if session is not None:
            headers["x-auth-token"] = str(session.get("token", ""))
            headers["x-cod-min"] = str(session.get("codMin", ""))
        try:
            async with self._session.post(
                FAMIGLIA_BASE + path, headers=headers, data=json.dumps(body), timeout=TIMEOUT
            ) as r:
                if r.status in (401, 403):
                    raise ArgoAuthError(f"{path}: HTTP {r.status}")
                if r.status != 200:
                    raise ArgoConnectionError(f"{path}: HTTP {r.status}")
                data = await r.json(content_type=None)
        except aiohttp.ClientError as err:
            raise ArgoConnectionError(str(err)) from err
        if not isinstance(data, dict):
            raise ArgoConnectionError(f"{path}: risposta inattesa")
        if data.get("success") is False:
            raise ArgoConnectionError(f"{path}: {data.get('message') or data.get('msg') or 'errore'}")
        return data

    async def _famiglia_session(self, profile: Profile) -> dict[str, Any]:
        await self._ensure_token()
        if not self._legacy and profile.token:
            # i profili vengono già dall'API Famiglia: la sessione è quella
            return {"token": profile.token, "codMin": profile.cod_min}
        if self._famiglia is None:
            data = await self._famiglia_api("login", {})
            items = data.get("data") or []
            self._famiglia = [i for i in (items if isinstance(items, list) else [items]) if isinstance(i, dict)]
        same_school = [p for p in self.profiles if p.cod_min == profile.cod_min]
        sessions = [s for s in self._famiglia if str(s.get("codMin", "")) == profile.cod_min] or self._famiglia
        idx = next((n for n, p in enumerate(same_school) if p.unique_id == profile.unique_id), 0)
        if not sessions:
            raise ArgoConnectionError("L'API Famiglia non ha restituito sessioni")
        return sessions[min(idx, len(sessions) - 1)]

    async def _session_for(self, profile: Profile) -> tuple[Profile, dict[str, Any]]:
        profile = next((p for p in self.profiles if p.unique_id == profile.unique_id), profile)
        try:
            session = await self._famiglia_session(profile)
        except ArgoAuthError:
            self._famiglia = None
            self._expires_at = 0
            session = await self._famiglia_session(profile)
        return profile, session

    async def _download(self, session: dict[str, Any], attachment_pk: str) -> bytes:
        link = await self._famiglia_api("famiglia/downloadallegatobacheca", {"uid": attachment_pk}, session)
        url = link.get("url")
        if not url:
            raise ArgoConnectionError("Argo non ha fornito il link dell'allegato")
        try:
            async with self._session.get(url, timeout=DOWNLOAD_TIMEOUT) as r:
                if r.status != 200:
                    raise ArgoConnectionError(f"Download allegato: HTTP {r.status}")
                if (r.content_length or 0) > MAX_ATTACHMENT_BYTES:
                    raise ArgoConnectionError("Allegato troppo grande")
                return await r.read()
        except aiohttp.ClientError as err:
            raise ArgoConnectionError(f"Download allegato: {err}") from err

    async def async_download_attachment(self, profile: Profile, attachment_pk: str) -> bytes:
        """Scarica un allegato della bacheca (Argo dà un link temporaneo che va usato subito)."""
        _, session = await self._session_for(profile)
        return await self._download(session, attachment_pk)

    async def async_confirm_notice(self, profile: Profile, notice_pk: str, attachment_pk: str | None) -> None:
        """Conferma la presa visione di una comunicazione della bacheca.

        Argo accetta la conferma solo dopo che almeno un allegato è stato scaricato,
        come farebbe un genitore dall'app: lo scarichiamo (e lo scartiamo) prima.
        """
        profile, session = await self._session_for(profile)
        if not profile.scheda_pk:
            raise ArgoConnectionError("Identificativo della scheda alunno non disponibile")
        if attachment_pk:
            await self._download(session, attachment_pk)
        await self._famiglia_api(
            "famiglia/presavisione", {"pkScheda": profile.scheda_pk, "prgMessaggio": notice_pk}, session
        )
