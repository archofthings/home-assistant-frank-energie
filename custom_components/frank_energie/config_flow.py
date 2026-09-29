"""Config flow for the Frank Energie integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_AUTHENTICATION,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
    CURRENCY_EURO,
    UnitOfEnergy,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from python_frank_energie import FrankEnergie
from python_frank_energie.exceptions import AuthException, AuthRequiredException, FrankEnergieException
from python_frank_energie.models import DeliverySite

from .const import (
    CONF_CHEAP_PRICE_THRESHOLD,
    CONF_CHEAPEST_PERIOD_MINUTES,
    CONF_EXPENSIVE_PRICE_THRESHOLD,
    CONF_PRICES_TIMEZONE,
    CONF_SENSOR_GROUPS,
    CONF_SOLAR_FORECAST_ENTRY,
    CONF_SOLAR_THRESHOLD_KWH,
    DEFAULT_CHEAP_PRICE_THRESHOLD,
    DEFAULT_CHEAPEST_PERIOD_MINUTES,
    DEFAULT_EXPENSIVE_PRICE_THRESHOLD,
    DEFAULT_SENSOR_GROUPS,
    DEFAULT_SOLAR_THRESHOLD_KWH,
    DOMAIN,
    LEGACY_SENSOR_GROUPS,
    PRICES_TIMEZONE_HOME_ASSISTANT,
    PRICES_TIMEZONE_UTC,
    SENSOR_GROUP_PRICE_ANALYSIS,
    SENSOR_GROUPS,
    SENSOR_GROUPS_REQUIRE_LOGIN,
    enabled_groups,
)
from .sites import build_site_title, discover_in_delivery_sites
from .solar_forecast import warn_energy_platforms_import_failed_once

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


def _price_number_selector(step: float, unit: str) -> selector.NumberSelector:
    """Build a box-mode NumberSelector for a price/threshold field."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(mode=selector.NumberSelectorMode.BOX, step=step, unit_of_measurement=unit)
    )


async def _solar_forecast_entry_options(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Build the solar_forecast_entry selector options.

    Options are the config entries whose domain provides an energy solar
    forecast platform (`async_get_solar_forecast`), labeled "<entry title>
    (<domain>)". Returns an empty list (never raises) if the energy
    websocket API can't be imported/queried for any reason. An import failure
    is logged as a WARNING once per Home Assistant run (shared with
    solar_forecast.py's own lookup); every other error stays at debug level.
    """
    try:
        try:
            from homeassistant.components.energy.websocket_api import (  # pylint: disable=import-outside-toplevel
                async_get_energy_platforms,
            )
        except ImportError as ex:
            warn_energy_platforms_import_failed_once(ex)
            return []

        platforms = await async_get_energy_platforms(hass)
    except Exception as ex:  # noqa: BLE001 - defensive; energy always ships with HA, but never break the form
        _LOGGER.debug("Could not determine solar forecast platforms: %s", ex)
        return []

    return [
        selector.SelectOptionDict(value=entry.entry_id, label=f"{entry.title} ({entry.domain})")
        for entry in hass.config_entries.async_entries()
        if entry.domain in platforms
    ]


def _init_schema(options: Mapping[str, Any], logged_in: bool) -> vol.Schema:
    """Build the options flow's "init" step schema: prices_timezone and sensor_groups.

    The SENSOR_GROUPS_REQUIRE_LOGIN groups ("costs", "daily_usage",
    "monthly_usage") are only offered as choices when the entry is logged in
    (has an access token); a public entry keeps whatever is currently stored
    for them, it just can't newly select them, so they are also left out of
    the default shown here (async_step_init adds them back to the submission).
    """
    current_groups = list(options.get(CONF_SENSOR_GROUPS, LEGACY_SENSOR_GROUPS))
    group_options = [group for group in SENSOR_GROUPS if group not in SENSOR_GROUPS_REQUIRE_LOGIN or logged_in]
    # The default must only contain values actually offered as choices:
    # SelectSelector validates each submitted item with vol.In(options), and
    # the frontend can't untick a value it can't see. This also guards
    # against stale/renamed values in current_groups.
    default_groups = [group for group in current_groups if group in group_options]

    return vol.Schema(
        {
            vol.Required(
                CONF_PRICES_TIMEZONE, default=options.get(CONF_PRICES_TIMEZONE, PRICES_TIMEZONE_UTC)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[PRICES_TIMEZONE_HOME_ASSISTANT, PRICES_TIMEZONE_UTC],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_PRICES_TIMEZONE,
                )
            ),
            vol.Required(CONF_SENSOR_GROUPS, default=default_groups): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=group_options,
                    mode=selector.SelectSelectorMode.LIST,
                    multiple=True,
                    translation_key=CONF_SENSOR_GROUPS,
                )
            ),
        }
    )


SECTION_PRICE_LEVELS = "price_levels"
SECTION_CHEAPEST_PERIOD = "cheapest_period"


def _price_levels_section_schema(
    options: Mapping[str, Any], solar_entry_options: list[selector.SelectOptionDict]
) -> vol.Schema:
    """Build the "price_levels" section schema: cheap/expensive thresholds and the solar forecast fields."""
    price_unit = f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}"
    schema: dict[Any, Any] = {
        vol.Required(
            CONF_CHEAP_PRICE_THRESHOLD,
            default=options.get(CONF_CHEAP_PRICE_THRESHOLD, DEFAULT_CHEAP_PRICE_THRESHOLD),
        ): _price_number_selector(0.001, price_unit),
        vol.Required(
            CONF_EXPENSIVE_PRICE_THRESHOLD,
            default=options.get(CONF_EXPENSIVE_PRICE_THRESHOLD, DEFAULT_EXPENSIVE_PRICE_THRESHOLD),
        ): _price_number_selector(0.001, price_unit),
    }

    # No `default=`: with a default, voluptuous puts it back whenever the
    # frontend omits the key (which it does for a cleared/empty
    # SelectSelector), making the choice impossible to clear. A
    # "suggested_value" pre-fills the form the same way without that
    # fallback-on-submit behaviour, and is only set when the currently
    # configured entry is still one of the valid choices: an id that no
    # longer resolves to a config entry would otherwise fail SelectSelector
    # validation and make the form impossible to submit at all.
    current_solar_entry = options.get(CONF_SOLAR_FORECAST_ENTRY)
    valid_solar_entries = {option["value"] for option in solar_entry_options}
    solar_forecast_entry_key = (
        vol.Optional(CONF_SOLAR_FORECAST_ENTRY, description={"suggested_value": current_solar_entry})
        if current_solar_entry in valid_solar_entries
        else vol.Optional(CONF_SOLAR_FORECAST_ENTRY)
    )
    schema[solar_forecast_entry_key] = selector.SelectSelector(
        selector.SelectSelectorConfig(options=solar_entry_options, mode=selector.SelectSelectorMode.DROPDOWN)
    )
    schema[
        vol.Required(
            CONF_SOLAR_THRESHOLD_KWH, default=options.get(CONF_SOLAR_THRESHOLD_KWH, DEFAULT_SOLAR_THRESHOLD_KWH)
        )
    ] = _price_number_selector(0.1, UnitOfEnergy.KILO_WATT_HOUR)

    return vol.Schema(schema)


def _cheapest_period_section_schema(options: Mapping[str, Any]) -> vol.Schema:
    """Build the "cheapest_period" section schema: the cheapest period length."""
    return vol.Schema(
        {
            vol.Required(
                CONF_CHEAPEST_PERIOD_MINUTES,
                default=options.get(CONF_CHEAPEST_PERIOD_MINUTES, DEFAULT_CHEAPEST_PERIOD_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    mode=selector.NumberSelectorMode.BOX, min=15, max=360, step=15, unit_of_measurement="min"
                )
            ),
        }
    )


def _analysis_schema(options: Mapping[str, Any], solar_entry_options: list[selector.SelectOptionDict]) -> vol.Schema:
    """Build the options flow's "analysis" step schema: two sections, price_levels and cheapest_period."""
    return vol.Schema(
        {
            vol.Required(SECTION_PRICE_LEVELS): section(
                _price_levels_section_schema(options, solar_entry_options), {"collapsed": False}
            ),
            vol.Required(SECTION_CHEAPEST_PERIOD): section(
                _cheapest_period_section_schema(options), {"collapsed": False}
            ),
        }
    )


def _flatten_analysis_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten a sectioned "analysis" step submission into a flat options dict.

    The stored option keys are unaffected by the sections (cosmetic UI
    grouping only): submitted values arrive nested per section
    (user_input[SECTION_PRICE_LEVELS][CONF_CHEAP_PRICE_THRESHOLD], ...) and
    are flattened back to the same flat keys used before sections existed.
    """
    return {**user_input[SECTION_PRICE_LEVELS], **user_input[SECTION_CHEAPEST_PERIOD]}


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
        self._pending_login_data: dict | None = None
        self._pending_sites: list[DeliverySite] | None = None
        self._reconfigure_sites: list[DeliverySite] | None = None
        self._reconfigure_api: FrankEnergie | None = None

    async def async_step_login(self, user_input=None, errors=None) -> ConfigFlowResult:
        """Handle login with credentials by user."""
        if not user_input:
            username = (
                self._get_reauth_entry().data.get(CONF_USERNAME) if self.source == SOURCE_REAUTH else None
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

            if self.source == SOURCE_REAUTH:
                return self._finish_reauth_login(data, user_input[CONF_USERNAME])

            # Check for a duplicate account before fetching sites, so a
            # duplicate login aborts immediately instead of making an
            # unnecessary UserSites() call (and, for multi-site accounts,
            # instead of making the user pick a site first).
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            return await self._async_discover_login_sites(api, data)

    def _finish_reauth_login(self, data: dict, new_username: str) -> ConfigFlowResult:
        """Merge a successful reauth login's tokens into the reauthenticated entry."""
        reauth_entry = self._get_reauth_entry()
        stored_username = reauth_entry.data.get(CONF_USERNAME)

        if stored_username is not None and not _same_account(stored_username, new_username):
            return self.async_abort(reason="wrong_account")

        return self.async_update_reload_and_abort(
            reauth_entry,
            data=_merge_reauth_data(
                reauth_entry.data, data, drop_site_reference=stored_username is None
            ),
        )

    async def _async_discover_login_sites(self, api: FrankEnergie, data: dict) -> ConfigFlowResult:
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

    async def async_step_site(self, user_input=None) -> ConfigFlowResult:
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

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
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

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Handle configuration by re-auth."""
        return await self.async_step_login()

    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
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
        runtime_data = getattr(entry, "runtime_data", None)
        if runtime_data is not None:
            return runtime_data.coordinator.api

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
    ) -> ConfigFlowResult:
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

    async def _async_create_entry(self, data: dict, title: str | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(data.get(CONF_USERNAME, "frank_energie"))
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=title or data.get(CONF_USERNAME, "Frank Energie"),
            data=data,
            options={
                CONF_PRICES_TIMEZONE: PRICES_TIMEZONE_HOME_ASSISTANT,
                CONF_SENSOR_GROUPS: list(DEFAULT_SENSOR_GROUPS),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlowWithReload):
    """Handle the Frank Energie options flow: sensor groups and, when selected, price analysis settings.

    Inherits from OptionsFlowWithReload so a changed option automatically
    reloads the config entry; do not also register an update listener in
    async_setup_entry for this (they cannot both be used at once).

    Two steps: "init" (prices_timezone, sensor_groups) is always shown first;
    "analysis" (the price analysis fields) only follows when price_analysis
    is among the selected sensor_groups. `_prices_timezone`/`_sensor_groups`
    carry the "init" step's submission over to "analysis", since both steps
    together produce a single options entry.
    """

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._prices_timezone: str | None = None
        self._sensor_groups: list[str] | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the "init" step: prices_timezone and sensor_groups."""
        if user_input is not None:
            self._prices_timezone = user_input[CONF_PRICES_TIMEZONE]
            self._sensor_groups = list(user_input[CONF_SENSOR_GROUPS])

            # SENSOR_GROUPS_REQUIRE_LOGIN groups aren't offered as choices for
            # a public entry (see _init_schema), so they're never part of the
            # submitted list; keep any of them already stored as is instead of
            # dropping them. Their sensors are skipped anyway while the entry
            # isn't authenticated.
            logged_in = self.config_entry.data.get(CONF_ACCESS_TOKEN) is not None
            if not logged_in:
                previously_enabled = enabled_groups(self.config_entry)
                for group in SENSOR_GROUPS_REQUIRE_LOGIN:
                    if group in previously_enabled and group not in self._sensor_groups:
                        self._sensor_groups.append(group)

            if SENSOR_GROUP_PRICE_ANALYSIS in self._sensor_groups:
                return await self.async_step_analysis()

            return self.async_create_entry(data=self._data_without_analysis())

        logged_in = self.config_entry.data.get(CONF_ACCESS_TOKEN) is not None
        return self.async_show_form(
            step_id="init", data_schema=_init_schema(self.config_entry.options, logged_in)
        )

    def _data_without_analysis(self) -> dict[str, Any]:
        """Build the options entry when price_analysis wasn't selected.

        Any previously stored price analysis options are kept as is, so
        re-enabling the group later restores them.
        """
        data: dict[str, Any] = {CONF_PRICES_TIMEZONE: self._prices_timezone, CONF_SENSOR_GROUPS: self._sensor_groups}
        for key in (
            CONF_CHEAP_PRICE_THRESHOLD,
            CONF_EXPENSIVE_PRICE_THRESHOLD,
            CONF_CHEAPEST_PERIOD_MINUTES,
            CONF_SOLAR_FORECAST_ENTRY,
            CONF_SOLAR_THRESHOLD_KWH,
        ):
            if key in self.config_entry.options:
                data[key] = self.config_entry.options[key]
        return data

    async def async_step_analysis(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the "analysis" step: the price analysis fields (only reached when price_analysis is selected)."""
        solar_entry_options = await _solar_forecast_entry_options(self.hass)

        if user_input is not None:
            flat_input = _flatten_analysis_input(user_input)
            if flat_input[CONF_CHEAP_PRICE_THRESHOLD] >= flat_input[CONF_EXPENSIVE_PRICE_THRESHOLD]:
                return self.async_show_form(
                    step_id="analysis",
                    data_schema=_analysis_schema(flat_input, solar_entry_options),
                    errors={"base": "thresholds_invalid"},
                )
            # NumberSelector always returns a float; cast back to int before
            # saving so find_cheapest_period() (which uses it in range()/
            # slicing) doesn't get handed a float.
            data = dict(flat_input)
            data[CONF_CHEAPEST_PERIOD_MINUTES] = int(data[CONF_CHEAPEST_PERIOD_MINUTES])
            data[CONF_PRICES_TIMEZONE] = self._prices_timezone
            data[CONF_SENSOR_GROUPS] = self._sensor_groups
            return self.async_create_entry(data=data)

        return self.async_show_form(
            step_id="analysis", data_schema=_analysis_schema(self.config_entry.options, solar_entry_options)
        )
