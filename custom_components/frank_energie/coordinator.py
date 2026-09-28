"""Coordinator implementation for Frank Energie integration."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TypedDict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from python_frank_energie import FrankEnergie
from python_frank_energie.exceptions import (
    AuthException,
    AuthRequiredException,
    FrankEnergieException,
    NoMarketPricesAvailableException,
    RequestException,
)
from python_frank_energie.models import PriceData, MonthSummary, Invoices, MarketPrices

from .const import DATA_ELECTRICITY, DATA_GAS, DATA_MONTH_SUMMARY, DATA_INVOICES

LOGGER = logging.getLogger(__name__)


class FrankEnergieData(TypedDict):
    DATA_ELECTRICITY: PriceData
    DATA_GAS: PriceData
    DATA_MONTH_SUMMARY: MonthSummary | None
    DATA_INVOICES: Invoices | None


class FrankEnergieCoordinator(DataUpdateCoordinator):
    """Get the latest data and update the states."""

    api: FrankEnergie

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: FrankEnergie,
    ) -> None:
        """Initialize the data object."""
        self.hass = hass
        self.entry = entry
        self.api = api
        self.site_reference = entry.data.get("site_reference", None)
        self._user_country: str | None = None

        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name="Frank Energie coordinator",
            update_interval=timedelta(minutes=60),
        )

    async def _async_update_data(self) -> FrankEnergieData:
        """Get the latest data from Frank Energie."""
        LOGGER.debug("Fetching Frank Energie data")

        # Prices are published per Frank Energie's market day, which is fixed
        # to Europe/Amsterdam regardless of the HA instance's own timezone.
        today = dt_util.now(dt_util.get_time_zone("Europe/Amsterdam")).date()

        try:
            prices_today = await self._fetch_prices_with_fallback(today)

            try:
                prices_tomorrow = await self._fetch_prices_with_fallback(today + timedelta(days=1))
            except NoMarketPricesAvailableException as ex:
                LOGGER.debug("No market prices available for tomorrow yet: %s", ex)
                prices_tomorrow = None

            data_month_summary = (
                await self.api.month_summary(self.site_reference) if self.api.is_authenticated else None
            )
            data_invoices = (
                await self.api.invoices(self.site_reference) if self.api.is_authenticated else None
            )
        except (AuthException, AuthRequiredException) as ex:
            LOGGER.debug("Authentication tokens expired, trying to renew them (%s)", ex)
            await self._try_renew_token()
            # Tell we have no data, so update coordinator tries again with renewed tokens
            return self._stale_data_or_raise(ex)

        except RequestException as ex:
            if str(ex).startswith("user-error:"):
                raise ConfigEntryAuthFailed from ex

            return self._stale_data_or_raise(ex)

        except FrankEnergieException as ex:
            # Any other library error (e.g. plain FrankEnergieException from a
            # 500 response or a validation error) should not crash the update;
            # fall back to stale data if we have any usable data cached.
            return self._stale_data_or_raise(ex)

        if self.api.is_authenticated:
            self._async_persist_tokens()

        tomorrow_electricity = prices_tomorrow.electricity if prices_tomorrow else None
        tomorrow_gas = prices_tomorrow.gas if prices_tomorrow else None

        return {
            DATA_ELECTRICITY: self._merge(prices_today.electricity, tomorrow_electricity),
            DATA_GAS: self._merge(prices_today.gas, tomorrow_gas),
            DATA_MONTH_SUMMARY: data_month_summary,
            DATA_INVOICES: data_invoices,
        }

    def _async_persist_tokens(self) -> None:
        """Persist tokens that the library renewed internally back into the config entry.

        python_frank_energie can silently renew the access/refresh tokens inside
        _query() when they are near expiry, updating only `api._auth` in memory.
        The library exposes no public getter for the current tokens (the `auth`
        property exists but logs a deprecation error on every access), so we
        read the private `_auth` attribute here instead.
        """
        auth = getattr(self.api, "_auth", None)
        if auth is None:
            return

        if (
            auth.authToken != self.entry.data.get(CONF_ACCESS_TOKEN)
            or auth.refreshToken != self.entry.data.get(CONF_TOKEN)
        ):
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={
                    **self.entry.data,
                    CONF_ACCESS_TOKEN: auth.authToken,
                    CONF_TOKEN: auth.refreshToken,
                },
            )

    def _stale_data_or_raise(self, ex: Exception) -> FrankEnergieData:
        """Return the last known data if it is still usable, otherwise raise UpdateFailed."""
        err = UpdateFailed(ex)

        if (
            self.data is not None
            and self.data[DATA_ELECTRICITY].upcoming_prices
            and self.data[DATA_GAS].upcoming_prices
        ):
            LOGGER.warning(str(err))
            return self.data

        raise err from ex

    @staticmethod
    def _merge(today: PriceData, tomorrow: PriceData | None) -> PriceData:
        """Merge today's and tomorrow's price data, when tomorrow is available."""
        if tomorrow is None or len(tomorrow.all) == 0:
            return today

        try:
            return today + tomorrow
        except ValueError as ex:
            # E.g. mismatched energy types/resolutions between today and tomorrow.
            LOGGER.warning("Could not merge today's and tomorrow's prices (%s), using today's prices only", ex)
            return today

    async def _get_user_country(self) -> str:
        """Fetch and cache the authenticated user's country code."""
        if self._user_country is None:
            me = await self.api.user_country()
            self._user_country = me.countryCode or "NL"

        return self._user_country

    async def _fetch_prices_with_fallback(self, start_date: date) -> MarketPrices:
        """Fetch prices for an authenticated or unauthenticated account.

        For authenticated accounts this prefers the user's contract prices, and
        falls back to public prices per-segment (electricity/gas) when either is
        missing.
        """
        if not self.api.is_authenticated:
            return await self.api.prices(start_date)

        user_country = await self._get_user_country()

        try:
            user_prices = await self.api.user_prices(self.site_reference, user_country, start_date)
        except NoMarketPricesAvailableException as ex:
            # No user prices at all for this date; treat it the same as an empty
            # response so the per-segment public-price fallback below kicks in
            # for both electricity and gas.
            LOGGER.info("No user prices available, falling back to public prices for both segments: %s", ex)
            user_prices = MarketPrices(
                electricity=PriceData([], energy_type="electricity"),
                gas=PriceData([], energy_type="gas"),
                energy_country=user_country,
            )

        if len(user_prices.gas.all) > 0 and len(user_prices.electricity.all) > 0:
            # If user_prices are available for both gas and electricity return them
            return user_prices

        await self._fill_missing_segments(user_prices, user_country, start_date)
        return user_prices

    async def _fill_missing_segments(
        self, user_prices: MarketPrices, user_country: str, start_date: date
    ) -> None:
        """Fill empty electricity/gas segments of `user_prices` with public prices, in place."""
        missing_gas = len(user_prices.gas.all) == 0
        missing_electricity = len(user_prices.electricity.all) == 0

        # The user's contract can use a different resolution than the public
        # prices' PT15M default (e.g. PT60M). When only one segment is missing,
        # request the public fallback at the resolution of the user's other,
        # non-empty segment so _merge() doesn't have to reconcile mismatched
        # resolutions later. When both segments are missing there is no
        # resolution to match, so fall back to the public default.
        if missing_gas and not missing_electricity:
            resolution = f"PT{user_prices.electricity.resolution_minutes}M"
        elif missing_electricity and not missing_gas:
            resolution = f"PT{user_prices.gas.resolution_minutes}M"
        else:
            resolution = "PT15M"

        public_prices = await self._fetch_public_prices(user_country, start_date, resolution)

        if missing_gas:
            LOGGER.info("No gas prices found for user, falling back to public prices")
            user_prices.gas = public_prices.gas

        if missing_electricity:
            LOGGER.info("No electricity prices found for user, falling back to public prices")
            user_prices.electricity = public_prices.electricity

            if len(user_prices.electricity.all) == 0:
                # Unlike gas (which some customers legitimately don't have),
                # every customer has electricity. If even the public fallback
                # has no electricity data, surface this as a real failure
                # (NoMarketPricesAvailableException is a RequestException, so
                # it is handled by _async_update_data's stale-data-or-raise
                # path) rather than silently handing sensors an empty series.
                raise NoMarketPricesAvailableException(
                    f"No electricity prices available (user or public) for {start_date}"
                )

    async def _fetch_public_prices(self, user_country: str, start_date: date, resolution: str) -> MarketPrices:
        """Fetch public market prices, using the country-specific query when needed."""
        if user_country == "NL":
            return await self.api.prices(start_date, resolution=resolution)

        return await self.api.country_prices(user_country, start_date, resolution=resolution)

    async def _try_renew_token(self):
        try:
            await self.api.renew_token()
            # renew_token() updates api._auth internally; persist it via the
            # same helper used for tokens renewed transparently inside _query(),
            # which preserves the rest of the entry's data (site_reference,
            # username, ...).
            self._async_persist_tokens()

            LOGGER.debug("Successfully renewed token")

        except (AuthException, AuthRequiredException) as ex:
            LOGGER.error("Failed to renew token: %s. Starting user reauth flow", ex)
            raise ConfigEntryAuthFailed from ex
