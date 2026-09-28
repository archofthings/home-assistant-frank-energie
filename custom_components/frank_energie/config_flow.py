"""Config flow for Picnic integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow, OptionsFlowWithReload
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_AUTHENTICATION,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from python_frank_energie import FrankEnergie
from python_frank_energie.exceptions import AuthException, AuthRequiredException, FrankEnergieException
from python_frank_energie.models import DeliverySite

from .const import CONF_COORDINATOR, CONF_PRICES_TIMEZONE, DOMAIN, PRICES_TIMEZONE_HOME_ASSISTANT, PRICES_TIMEZONE_UTC
from .sites import build_site_title, discover_in_delivery_sites

_LOGGER = logging.getLogger(__name__)

SITE_REFERENCE = "site_reference"


def _same_account(stored_username: str | None, new_username: str) -> bool:
    """Return whether a stored username and a new login refer to the same account.

    Comparison is normalised with .strip().casefold(). Returns False when
    there is no stored username to compare against (legacy entries).
    """
    return (
        stored_username is not None
        and stored_username.strip().casefold() == new_username.strip().casefold()
    )


def _merge_reauth_data(entry_data: Mapping[str, Any], new_data: dict, *, drop_site_reference: bool) -> dict:
    """Merge new login data into the existing entry data for a reauth login.

    drop_site_reference is True only for legacy entries with no stored
    username to compare against: since we can't confirm it's the same
    account, "site_reference" is dropped so it doesn't make price/cost
    requests fail for a possibly different account; async_setup_entry then
    rediscovers the site. For a same-account login (the only other case that
    reaches this helper) the existing entry data, including site_reference,
    is kept as is. The unique_id is left untouched either way.
    """
    base = dict(entry_data)

    if drop_site_reference:
        base.pop(SITE_REFERENCE, None)

    return {**base, **new_data}


def _prices_timezone_schema(default: str) -> vol.Schema:
    """Build the options flow schema for the prices_timezone field."""
    return vol.Schema(
        {
            vol.Required(CONF_PRICES_TIMEZONE, default=default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[PRICES_TIMEZONE_HOME_ASSISTANT, PRICES_TIMEZONE_UTC],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_PRICES_TIMEZONE,
                )
            )
        }
    )


def _site_selection_schema(sites: list[DeliverySite], default: str | None = None) -> vol.Schema:
    """Build a schema with a dropdown to choose one of `sites` by reference."""
    options = [
        selector.SelectOptionDict(value=site.reference, label=build_site_title(site) or site.reference)
        for site in sites
    ]
    return vol.Schema(
        {
            vol.Required(SITE_REFERENCE, default=default): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
            )
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Frank Energie."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._reauth_entry = None
        self._pending_login_data: dict | None = None
        self._pending_sites: list[DeliverySite] | None = None
        self._reconfigure_sites: list[DeliverySite] | None = None
        self._reconfigure_api: FrankEnergie | None = None

    async def async_step_login(self, user_input=None, errors=None) -> FlowResult:
        """Handle login with credentials by user."""
        if not user_input:
            username = (
                self._reauth_entry.data.get(CONF_USERNAME) if self._reauth_entry else None
            )

            data_schema = vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=username): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            )

            return self.async_show_form(
                step_id="login",
                data_schema=data_schema,
                errors=errors,
            )

        async with FrankEnergie() as api:
            try:
                auth = await api.login(
                    user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except AuthException as ex:
                _LOGGER.exception("Error during login", exc_info=ex)
                return await self.async_step_login(errors={"base": "invalid_auth"})
            except FrankEnergieException as ex:
                _LOGGER.exception("Error during login", exc_info=ex)
                return await self.async_step_login(errors={"base": "cannot_connect"})

            data = {
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_ACCESS_TOKEN: auth.authToken,
                CONF_TOKEN: auth.refreshToken,
            }

            if self._reauth_entry:
                return self._finish_reauth_login(data, user_input[CONF_USERNAME])

            # Check for a duplicate account before fetching sites, so a
            # duplicate login aborts immediately instead of making an
            # unnecessary UserSites() call (and, for multi-site accounts,
            # instead of making the user pick a site first).
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            return await self._async_discover_login_sites(api, data)

    def _finish_reauth_login(self, data: dict, new_username: str) -> FlowResult:
        """Merge a successful reauth login's tokens into the reauthenticated entry."""
        stored_username = self._reauth_entry.data.get(CONF_USERNAME)

        if stored_username is not None and not _same_account(stored_username, new_username):
            return self.async_abort(reason="wrong_account")

        return self.async_update_reload_and_abort(
            self._reauth_entry,
            data=_merge_reauth_data(
                self._reauth_entry.data, data, drop_site_reference=stored_username is None
            ),
        )

    async def _async_discover_login_sites(self, api: FrankEnergie, data: dict) -> FlowResult:
        """Discover the delivery sites for a fresh (non-reauth) login and proceed accordingly."""
        try:
            user_sites = await api.UserSites()
        except (AuthException, AuthRequiredException) as ex:
            _LOGGER.exception("Error loading sites during login", exc_info=ex)
            return await self.async_step_login(errors={"base": "invalid_auth"})
        except FrankEnergieException as ex:
            _LOGGER.exception("Error loading sites during login", exc_info=ex)
            return await self.async_step_login(errors={"base": "cannot_connect"})

        sites = discover_in_delivery_sites(user_sites)

        if not sites:
            return self.async_abort(reason="no_sites")

        if len(sites) == 1:
            site = sites[0]
            return await self._async_create_entry(
                {**data, SITE_REFERENCE: site.reference},
                title=build_site_title(site) or data[CONF_USERNAME],
            )

        self._pending_login_data = data
        self._pending_sites = sites
        return await self.async_step_site()

    async def async_step_site(self, user_input=None) -> FlowResult:
        """Let the user pick which delivery site to use, when login found more than one."""
        if user_input is None:
            return self.async_show_form(
                step_id="site",
                data_schema=_site_selection_schema(self._pending_sites),
            )

        chosen_reference = user_input[SITE_REFERENCE]
        site = next((s for s in self._pending_sites if s.reference == chosen_reference), None)
        data = {**self._pending_login_data, SITE_REFERENCE: chosen_reference}

        return await self._async_create_entry(
            data, title=(build_site_title(site) if site else None) or data[CONF_USERNAME]
        )

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle a flow initiated by the user."""
        if not user_input:
            data_schema = vol.Schema(
                {
                    vol.Required(CONF_AUTHENTICATION): bool,
                }
            )

            return self.async_show_form(step_id="user", data_schema=data_schema)

        if user_input[CONF_AUTHENTICATION]:
            return await self.async_step_login()

        data = {}

        return await self._async_create_entry(data)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle configuration by re-auth."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_login()

    async def async_step_reconfigure(self, user_input=None) -> FlowResult:
        """Let the user change which delivery site an already-configured entry uses.

        UserSites() is fetched only once, when the form is first shown (and
        its result, plus the client used, kept on the flow); submitting the
        form does not fetch again, since the selector already constrains the
        choice to one of those sites. This avoids both losing tokens the
        client renews mid-flow and racing a parallel renewal (with the same
        refresh token) by the entry's own running coordinator.
        """
        entry = self._get_reconfigure_entry()

        if entry.data.get(CONF_ACCESS_TOKEN) is None:
            return self.async_abort(reason="reconfigure_not_supported")

        if self._reconfigure_sites is None:
            api = self._reconfigure_client(entry)
            sites, errors = await self._fetch_reconfigure_sites(api)

            if errors is not None:
                return self.async_abort(reason="cannot_connect")

            if not sites:
                return self.async_abort(reason="no_sites")

            self._reconfigure_api = api
            self._reconfigure_sites = sites

        if user_input is not None:
            return self._finish_reconfigure(
                entry, self._reconfigure_api, self._reconfigure_sites, user_input[SITE_REFERENCE]
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_site_selection_schema(self._reconfigure_sites, entry.data.get(SITE_REFERENCE)),
        )

    def _reconfigure_client(self, entry: ConfigEntry) -> FrankEnergie:
        """Return the API client to use for the reconfigure flow.

        Reuses the running coordinator's client when the entry is loaded,
        since the coordinator already persists any tokens that client renews
        (see FrankEnergieCoordinator._async_persist_tokens()). A new client is
        only built when the entry isn't loaded (e.g. it is in SETUP_RETRY).
        """
        loaded = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if loaded is not None:
            return loaded[CONF_COORDINATOR].api

        return FrankEnergie(
            clientsession=async_get_clientsession(self.hass),
            auth_token=entry.data.get(CONF_ACCESS_TOKEN),
            refresh_token=entry.data.get(CONF_TOKEN),
        )

    @staticmethod
    async def _fetch_reconfigure_sites(api: FrankEnergie) -> tuple[list[DeliverySite] | None, dict | None]:
        """Fetch delivery sites for the reconfigure flow. Returns (sites, errors)."""
        try:
            user_sites = await api.UserSites()
        except (AuthException, AuthRequiredException) as ex:
            _LOGGER.exception("Error loading sites during reconfigure", exc_info=ex)
            return None, {"base": "invalid_auth"}
        except FrankEnergieException as ex:
            _LOGGER.exception("Error loading sites during reconfigure", exc_info=ex)
            return None, {"base": "cannot_connect"}

        return discover_in_delivery_sites(user_sites), None

    def _finish_reconfigure(
        self, entry: ConfigEntry, api: FrankEnergie, sites: list[DeliverySite], chosen_reference: str
    ) -> FlowResult:
        """Persist the chosen site (and any renewed tokens) and reload the entry."""
        site = next((s for s in sites if s.reference == chosen_reference), None)
        title = build_site_title(site) if site else entry.title
        new_data = {**entry.data, SITE_REFERENCE: chosen_reference}

        # python_frank_energie can silently renew the access/refresh tokens
        # inside UserSites() when they are near expiry, updating only
        # `api._auth` in memory. Persist them the same way
        # FrankEnergieCoordinator._async_persist_tokens() does, so a renewed
        # token from this reconfigure flow is never lost.
        auth = getattr(api, "_auth", None)
        if auth is not None:
            new_data[CONF_ACCESS_TOKEN] = auth.authToken
            new_data[CONF_TOKEN] = auth.refreshToken

        return self.async_update_reload_and_abort(entry, data=new_data, title=title)

    async def _async_create_entry(self, data: dict, title: str | None = None) -> FlowResult:
        await self.async_set_unique_id(data.get(CONF_USERNAME, "frank_energie"))
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=title or data.get(CONF_USERNAME, "Frank Energie"),
            data=data,
            options={CONF_PRICES_TIMEZONE: PRICES_TIMEZONE_HOME_ASSISTANT},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlowWithReload):
    """Handle the Frank Energie options flow (currently just the prices_timezone field).

    Inherits from OptionsFlowWithReload so a changed option automatically
    reloads the config entry; do not also register an update listener in
    async_setup_entry for this (they cannot both be used at once).
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the single options step: choose the prices_timezone."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        default = self.config_entry.options.get(CONF_PRICES_TIMEZONE, PRICES_TIMEZONE_UTC)
        return self.async_show_form(step_id="init", data_schema=_prices_timezone_schema(default))
