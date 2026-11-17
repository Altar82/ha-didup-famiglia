"""Test offline: flusso di login simulato e parsing della dashboard."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

BASE = Path(__file__).resolve().parent.parent / "custom_components" / "didup_famiglia"

# aiohttp finto se non installato (serve solo per gli import)
if "aiohttp" not in sys.modules:
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        fake = types.ModuleType("aiohttp")

        class ClientError(Exception):
            pass

        fake.ClientError = ClientError
        fake.ClientTimeout = lambda **kw: None
        fake.ClientSession = object
        fake.CookieJar = object
        sys.modules["aiohttp"] = fake


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


api = _load("api")
parse = _load("parse")


# --------------------------------------------------------------- fake Argo
class _Resp:
    def __init__(self, status, body="", location=None, url="", js=None):
        self.status, self._body, self.url, self._js = status, body, url, js
        self.headers = {"Location": location} if location else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def text(self, errors=None):
        return self._body

    async def json(self, content_type=None):
        return self._js

    async def read(self):
        return self._body


class _Jar:
    def clear(self):
        pass


class FakeArgo:
    """Simula il comportamento di Argo di novembre 2026 (pagina consent con HTTP 200)."""

    def __init__(self, password="giusta", consent_as_form=False):
        self.cookie_jar = _Jar()
        self.closed = False
        self.password = password
        self.consent_as_form = consent_as_form
        self.state = None
        self.calls = []

    def get(self, url, params=None, **kw):
        if params:
            url = f"{url}?{urlencode(params)}"
        self.calls.append(("GET", url))
        p = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(p.query).items()}
        if p.path == "/oauth2/auth" and "consent_verifier" in q:
            return _Resp(302, location=f"{api.REDIRECT_URI}?code=CODE123&state={self.state}", url=url)
        if p.path == "/oauth2/auth":
            self.state = q["state"]
            return _Resp(302, location="https://www.portaleargo.it/auth/sso/login/?login_challenge=CH1", url=url)
        if p.path.startswith("/auth/sso/login"):
            return _Resp(200, "<form><input type=password name=password></form>", url=url)
        if p.path.startswith("/auth/sso/consent"):
            return _Resp(
                200,
                '<form method="post" action="/auth/sso/consent/"><input type=hidden name=consent_challenge value=CC>'
                '<button name="accept" value="true">Ok</button></form>',
                url=url,
            )
        return _Resp(404, url=url)

    def post(self, url, data=None, **kw):
        self.calls.append(("POST", url, data))
        if url == api.SSO_LOGIN_URL:
            if data["password"] != self.password or data["challenge"] != "CH1":
                return _Resp(200, "<p>Credenziali errate</p><input type='password' name='password'>", url=url)
            if self.consent_as_form:
                return _Resp(302, location="/auth/sso/consent/?consent_challenge=CC", url=url)
            link = (
                "https://auth.portaleargo.it/oauth2/auth?client_id="
                f"{api.CLIENT_ID}&consent_verifier=V1&state={self.state}&amp;x=1"
            )
            return _Resp(200, f'<html><a href="{link}">Continua</a></html>', url=url)
        if url.endswith("/auth/sso/consent/"):
            assert data.get("accept") == "true"
            return _Resp(
                302,
                location=f"https://auth.portaleargo.it/oauth2/auth?client_id={api.CLIENT_ID}&consent_verifier=V2&state={self.state}",
                url=url,
            )
        if url == api.TOKEN_URL:
            if data["grant_type"] == "refresh_token":
                if data["refresh_token"] == "SCADUTO":
                    return _Resp(400, url=url)
                return _Resp(200, js={"access_token": "AT", "refresh_token": "RT-NUOVO", "expires_in": 3600}, url=url)
            if data["code"] != "CODE123":
                return _Resp(400, url=url)
            return _Resp(200, js={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}, url=url)
        return _Resp(404, url=url)

    def request(self, method, url, headers=None, data=None, **kw):
        self.calls.append((method, url, headers))
        assert headers["Authorization"] == "Bearer AT"
        if url.endswith("/login"):
            return _Resp(200, js={"success": True, "data": [{"token": "PT", "codMin": "SC1", "opzioni": []}]})
        if url.endswith("/profilo"):
            return _Resp(
                200,
                js={"success": True, "data": {"alunno": {"nominativo": "ROSSI MARIO", "pk": "42"},
                    "scheda": {"classe": {"desDenominazione": "3", "desSezione": "B"}}}},
            )
        if url.endswith("dashboard/dashboard"):
            assert headers["x-auth-token"] == "PT"
            return _Resp(200, js={"success": True, "data": {"dati": [DASH]}})
        return _Resp(404)


DASH = {
    "mediaGenerale": 7.25,
    "voti": [
        {"pk": "v1", "datGiorno": "2026-11-10", "desMateria": "MATEMATICA", "codVoto": "7½", "valore": 7.5,
         "codVotoPratico": "S", "docente": "(Prof. BIANCHI LUCA)", "numMedia": 1},
        {"pk": "v2", "datGiorno": "2026-11-12", "desMateria": "ITALIANO", "codVoto": "6-", "valore": 0},
        {"pk": "v3", "datGiorno": "2026-11-01", "desMateria": "ITALIANO", "codVoto": "8", "operazione": "D"},
    ],
    "registro": [
        {"pk": "r1", "datGiorno": "2026-11-13", "desMateria": "STORIA",
         "compiti": [{"compito": "Studiare pag. 40", "dataConsegna": "2026-11-16"}]},
    ],
    "promemoria": [{"pk": "p1", "datGiorno": "2026-11-20", "desAnnotazioni": "Uscita didattica"}],
    "appello": [
        {"pk": "a1", "data": "2026-11-03", "codEvento": "A", "daGiustificare": True, "giustificata": "N"},
        {"pk": "a2", "data": "2026-11-05", "codEvento": "I", "daGiustificare": False},
    ],
    "noteDisciplinari": [{"pk": "n1", "datNota": "2026-11-07", "desNota": "Disturba", "flgVisto": False}],
    "bacheca": [
        {"pk": "b1", "data": "2026-11-11", "messaggio": "Sciopero", "pvRichiesta": True, "isPresaVisione": False,
         "listaAllegati": [{"nomeFile": "circ.pdf"}]},
        {"pk": "b2", "data": "2026-11-01", "messaggio": "Info", "pvRichiesta": False},
    ],
}


def _client(fake):
    return api.ArgoClient(fake, "1.30.2", school_code="sc1", username="user", password="giusta")


def test_login_consent_link():
    fake = FakeArgo()
    profiles = asyncio.run(_client(fake).async_login())
    assert profiles[0].name == "ROSSI MARIO"
    assert profiles[0].class_name == "3 B"
    assert profiles[0].unique_id == "SC1_42"
    token_call = next(c for c in fake.calls if c[0] == "POST" and c[1] == api.TOKEN_URL)
    assert token_call[2]["code"] == "CODE123"
    assert token_call[2]["code_verifier"]


def test_login_consent_form():
    fake = FakeArgo(consent_as_form=True)
    asyncio.run(_client(fake).async_login())
    assert any(c[0] == "POST" and c[1].endswith("/auth/sso/consent/") for c in fake.calls)


def test_wrong_password():
    fake = FakeArgo(password="altra")
    try:
        asyncio.run(_client(fake).async_login())
    except api.ArgoAuthError:
        return
    raise AssertionError("doveva fallire")


def test_rejects_foreign_continuation():
    html = '<a href="https://evil.example/oauth2/auth?consent_verifier=1">x</a>'
    assert api.find_continuation(html, "https://www.portaleargo.it/", "s") is None
    html = f'<a href="https://auth.portaleargo.it/oauth2/auth?consent_verifier=1&state=altro&client_id={api.CLIENT_ID}">x</a>'
    assert api.find_continuation(html, "https://www.portaleargo.it/", "s") is None


def test_dashboard_and_parse():
    fake = FakeArgo()
    c = _client(fake)
    p = asyncio.run(c.async_login())[0]
    raw = asyncio.run(c.async_get_dashboard(p))
    d = parse.parse_dashboard(raw)
    assert [g.pk for g in d.grades] == ["v2", "v1"]  # D esclusa, ordine per data desc
    assert d.grades[0].value == 5.75  # 6- con valore 0 -> ricavato dal codice
    assert d.grades[1].kind == "scritto" and d.grades[1].teacher == "Prof. BIANCHI LUCA"
    assert d.average == 7.25
    assert d.subject_averages == {"ITALIANO": 5.75, "MATEMATICA": 7.5}
    assert d.homework[0].due == date(2026, 11, 16) and d.homework[0].subject == "STORIA"
    assert d.reminders[0].text == "Uscita didattica"
    assert [a.kind for a in d.absences] == ["ritardo", "assenza"]
    assert sum(a.to_justify for a in d.absences) == 1
    assert d.notes[0].text == "Disturba"
    assert [n.unread for n in d.notices] == [True, False]
    assert d.notices[0].attachments == ["circ.pdf"]


def test_grade_values():
    assert parse.grade_value("7½") == 7.5
    assert parse.grade_value("6+") == 6.25
    assert parse.grade_value("6/7") == 6.5
    assert parse.grade_value("10") == 10
    assert parse.grade_value("ottimo") is None


# --------------------------------------------------------------- SPID / CIE
def test_spid_browser_login_and_refresh():
    url, verifier, state = api.build_authorize_url()
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"][0] == api.REDIRECT_URI and q["state"][0] == state
    assert q["code_challenge_method"][0] == "S256"

    fake = FakeArgo()
    saved = []
    c = api.ArgoClient(fake, "1.30.2", on_refresh_token=saved.append)
    callback = f"{api.REDIRECT_URI}?code=CODE123&scope=openid&state={state}"
    profiles = asyncio.run(c.async_login_with_callback(callback, verifier, state))
    assert profiles[0].name == "ROSSI MARIO"
    assert profiles[0].unique_id == "SC1_42"  # stesso id della modalità credenziali
    assert saved == ["RT"]
    token_call = next(x for x in fake.calls if x[0] == "POST" and x[1] == api.TOKEN_URL)
    assert token_call[2]["code_verifier"] == verifier

    # riavvio di HA: si riparte dal solo refresh token, che viene ruotato e salvato
    fake2 = FakeArgo()
    saved2 = []
    c2 = api.ArgoClient(fake2, "1.30.2", refresh_token="RT", on_refresh_token=saved2.append)
    assert asyncio.run(c2.async_login())[0].name == "ROSSI MARIO"
    assert saved2 == ["RT-NUOVO"]
    assert not any(x[1] == api.SSO_LOGIN_URL for x in fake2.calls if len(x) > 1)


def test_spid_expired_refresh_requires_reauth():
    c = api.ArgoClient(FakeArgo(), "1.30.2", refresh_token="SCADUTO")
    try:
        asyncio.run(c.async_login())
    except api.ArgoAuthError:
        return
    raise AssertionError("doveva chiedere un nuovo accesso")


def test_parse_callback_variants():
    st = "abc"
    assert api.parse_callback(f"{api.REDIRECT_URI}?code=XYZ&state=abc", st) == "XYZ"
    assert api.parse_callback(f"'{api.REDIRECT_URI}?code=XYZ&state=abc'", st) == "XYZ"
    assert api.parse_callback("code=XYZ&state=abc", st) == "XYZ"
    for bad in ("ciao", f"{api.REDIRECT_URI}?code=XYZ&state=altro", "https://evil.example/?code=1&state=abc"):
        try:
            api.parse_callback(bad, st)
        except (api.ArgoConnectionError, api.ArgoAuthError):
            continue
        raise AssertionError(bad)


def test_diagnostica_oscura_token_e_nomi():
    """Il file di diagnostica non deve contenere il refresh token né nomi di persone."""
    import ast
    import pathlib

    base = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "didup_famiglia"
    albero = ast.parse((base / "diagnostics.py").read_text())
    voci = next(
        n.value for n in albero.body
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "TO_REDACT"
    )
    nomi = {e.id if isinstance(e, ast.Name) else e.value for e in voci.elts}
    assert {"CONF_REFRESH_TOKEN", "CONF_CALLBACK_URL", "CONF_PASSWORD", "CONF_USERNAME"} <= nomi
    assert {"docente", "desDocente", "autore", "nominativo", "nome", "cognome"} <= nomi


class FakeFamiglia:
    """API Famiglia simulata: la conferma passa solo dopo aver scaricato un allegato."""

    def __init__(self):
        self.cookie_jar = _Jar()
        self.calls = []
        self.scaricato = False

    def post(self, url, data=None, headers=None, **kw):
        import json as _j

        body = _j.loads(data) if data else {}
        self.calls.append((url.removeprefix(api.FAMIGLIA_BASE), body, dict(headers or {})))
        if url.endswith("/login"):
            return _Resp(200, js={"success": True, "data": [{"token": "FT", "codMin": "SC1"}]})
        if url.endswith("downloadallegatobacheca"):
            return _Resp(200, js={"success": True, "url": "https://files.example/a.pdf"})
        if url.endswith("famiglia/presavisione"):
            if not self.scaricato:
                return _Resp(200, js={"success": False, "msg": "Per confermare scarica un allegato"})
            return _Resp(200, js={"success": True})
        return _Resp(404)

    def get(self, url, **kw):
        self.scaricato = True
        return _Resp(200, b"pdf")


def test_presa_visione_scarica_allegato_e_conferma():
    fake = FakeFamiglia()
    c = api.ArgoClient(fake, "1.30.2", refresh_token="RT")
    c._access_token, c._expires_at = "AT", 9e18
    p = api.Profile(token="T", cod_min="SC1", student_id="sc1_1", scheda_pk="SK9")
    c.profiles = [p]
    asyncio.run(c.async_confirm_notice(p, "777", "ALL1"))
    paths = [x[0] for x in fake.calls]
    assert paths == ["login", "famiglia/downloadallegatobacheca", "famiglia/presavisione"]
    assert fake.calls[-1][1] == {"pkScheda": "SK9", "prgMessaggio": "777"}
    assert fake.calls[-1][2]["x-auth-token"] == "FT"
    # senza allegato Argo rifiuta e l'errore arriva chiaro
    fake2 = FakeFamiglia()
    c2 = api.ArgoClient(fake2, "1.30.2", refresh_token="RT")
    c2._access_token, c2._expires_at, c2.profiles = "AT", 9e18, [p]
    try:
        asyncio.run(c2.async_confirm_notice(p, "778", None))
    except api.ArgoConnectionError as err:
        assert "allegato" in str(err)
    else:
        raise AssertionError("doveva fallire")


def test_bacheca_id_allegati_e_promemoria():
    dash = {
        "bacheca": [
            {"pk": "9", "data": "2026-11-10", "messaggio": "Uscita", "pvRichiesta": True,
             "listaAllegati": [{"pk": "A1", "nomeFile": "c.pdf"}]},
        ],
        "promemoria": [
            {"pk": "2", "datGiorno": "2026-11-20", "desAnnotazioni": "Verifica storia"},
            {"pk": "1", "datGiorno": "2026-11-18", "desAnnotazioni": "Interrogazione"},
        ],
    }
    d = parse.parse_dashboard(dash)
    n = d.notices[0]
    assert n.attachment_ids == ["A1"] and n.as_dict()["id"] == "9" and n.unread
    assert [r.text for r in d.reminders] == ["Interrogazione", "Verifica storia"]
    assert d.reminders[0].as_dict()["data"] == "2026-11-18"
