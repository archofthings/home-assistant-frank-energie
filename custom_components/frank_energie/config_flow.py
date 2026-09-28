"""Config flow for Picnic integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_AUTHENTICATION,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
)
from homeassistant.data_entry_flow import FlowResult
from python_frank_energie import FrankEnergie
from python_frank_energie.exceptions import AuthException, FrankEnergieException

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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
        base.pop("site_reference", None)

    return {**base, **new_data}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Frank Energie."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._reauth_entry = None

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
            stored_username = self._reauth_entry.data.get(CONF_USERNAME)

            if stored_username is not None and not _same_account(stored_username, user_input[CONF_USERNAME]):
                return self.async_abort(reason="wrong_account")

            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data=_merge_reauth_data(
                    self._reauth_entry.data, data, drop_site_reference=stored_username is None
                ),
            )

        await self.async_set_unique_id(user_input[CONF_USERNAME])
        self._abort_if_unique_id_configured()

        return await self._async_create_entry(data)

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

    async def _async_create_entry(self, data):
        await self.async_set_unique_id(data.get(CONF_USERNAME, "frank_energie"))
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=data.get(CONF_USERNAME, "Frank Energie"), data=data
        )
