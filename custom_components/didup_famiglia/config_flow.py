"""Config flow per DidUP Famiglia: credenziali Argo oppure SPID/CIE."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback

from .api import (
    ArgoAuthError,
    ArgoConnectionError,
    ArgoOutdatedClientError,
    Profile,
    build_authorize_url,
    parse_callback,
)
from .const import (
    AUTH_CREDENTIALS,
    AUTH_SPID,
    CONF_AUTH_METHOD,
    CONF_CALLBACK_URL,
    CONF_CLIENT_VERSION,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SCHOOL_CODE,
    DEFAULT_CLIENT_VERSION,
    DEFAULT_SCAN_INTERVAL_MIN,
    DOMAIN,
    MIN_SCAN_INTERVAL_MIN,
)
from .coordinator import make_client

_LOGGER = logging.getLogger(__name__)

CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCHOOL_CODE): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)
SPID_SCHEMA = vol.Schema({vol.Required(CONF_CALLBACK_URL): str})


def _names(profiles: list[Profile]) -> str:
    return ", ".join(p.name or "?" for p in profiles)


class DidupConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._auth: tuple[str, str, str] | None = None  # (url, verifier, state)

    # ------------------------------------------------------------ helpers
    async def _run(self, coro_factory, data: dict[str, Any], options: dict[str, Any] | None = None):
        """Esegue un login e traduce le eccezioni in codici d'errore del form."""
        client = make_client(self.hass, data, options)
        try:
            profiles = await coro_factory(client)
            return None, profiles, client.refresh_token
        except ArgoAuthError as err:
            _LOGGER.info("Accesso Argo rifiutato: %s", err)
            return "invalid_auth", [], None
        except ArgoOutdatedClientError:
            return "outdated_client", [], None
        except ArgoConnectionError as err:
            _LOGGER.warning("Login Argo fallito: %s", err)
            return "cannot_connect", [], None
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Errore inatteso durante il login Argo")
            return "unknown", [], None
        finally:
            await client.async_close()

    def _spid_url(self) -> str:
        if self._auth is None:
            self._auth = build_authorize_url()
        return self._auth[0]

    async def _spid_login(self, callback_text: str, options: dict[str, Any] | None = None):
        _, verifier, state = self._auth  # type: ignore[misc]
        try:
            parse_callback(callback_text, state)
        except (ArgoAuthError, ArgoConnectionError) as err:
            _LOGGER.info("Indirizzo di ritorno non valido: %s", err)
            return "invalid_callback", [], None

        async def go(client):
            return await client.async_login_with_callback(callback_text, verifier, state)

        error, profiles, refresh = await self._run(go, {}, options)
        if error == "invalid_auth":
            # il codice vale pochi minuti e una sola volta
            error = "code_expired"
        return error, profiles, refresh

    # ------------------------------------------------------------ setup
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=[AUTH_CREDENTIALS, AUTH_SPID])

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_SCHOOL_CODE] = user_input[CONF_SCHOOL_CODE].strip().upper()
            user_input[CONF_USERNAME] = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(f"{user_input[CONF_SCHOOL_CODE]}_{user_input[CONF_USERNAME]}".lower())
            self._abort_if_unique_id_configured()
            error, profiles, _ = await self._run(lambda c: c.async_login(), user_input)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"{user_input[CONF_SCHOOL_CODE]} · {_names(profiles)}",
                    data={**user_input, CONF_AUTH_METHOD: AUTH_CREDENTIALS},
                )
        return self.async_show_form(
            step_id="credentials",
            data_schema=self.add_suggested_values_to_schema(CREDENTIALS_SCHEMA, user_input or {}),
            errors=errors,
        )

    async def async_step_spid(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        url = self._spid_url()
        if user_input is not None:
            error, profiles, refresh = await self._spid_login(user_input[CONF_CALLBACK_URL])
            if error:
                errors["base"] = error
            elif not refresh:
                errors["base"] = "no_refresh_token"
            else:
                ids = "_".join(sorted(p.unique_id for p in profiles))
                await self.async_set_unique_id(f"spid_{ids}".lower())
                self._abort_if_unique_id_configured(updates={CONF_REFRESH_TOKEN: refresh})
                return self.async_create_entry(
                    title=f"SPID/CIE · {_names(profiles)}",
                    data={
                        CONF_AUTH_METHOD: AUTH_SPID,
                        CONF_REFRESH_TOKEN: refresh,
                        CONF_SCHOOL_CODE: profiles[0].cod_min,
                    },
                )
        return self.async_show_form(
            step_id="spid",
            data_schema=SPID_SCHEMA,
            description_placeholders={"url": url},
            errors=errors,
        )

    # ------------------------------------------------------------ reauth
    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        if entry_data.get(CONF_AUTH_METHOD) == AUTH_SPID:
            return await self.async_step_reauth_spid()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            error, _, _ = await self._run(lambda c: c.async_login(), data, dict(entry.options))
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": entry.data.get(CONF_USERNAME, "")},
            errors=errors,
        )

    async def async_step_reauth_spid(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        url = self._spid_url()
        if user_input is not None:
            error, _, refresh = await self._spid_login(user_input[CONF_CALLBACK_URL], dict(entry.options))
            if error:
                errors["base"] = error
            elif not refresh:
                errors["base"] = "no_refresh_token"
            else:
                return self.async_update_reload_and_abort(entry, data={**entry.data, CONF_REFRESH_TOKEN: refresh})
        return self.async_show_form(
            step_id="reauth_spid",
            data_schema=SPID_SCHEMA,
            description_placeholders={"url": url},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DidupOptionsFlow()


class DidupOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MIN)
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL_MIN, max=720)),
                    vol.Required(
                        CONF_CLIENT_VERSION, default=opts.get(CONF_CLIENT_VERSION, DEFAULT_CLIENT_VERSION)
                    ): str,
                }
            ),
        )
