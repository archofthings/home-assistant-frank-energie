"""Coordinator implementation for Frank Energie integration."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, tzinfo
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

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

from .const import (
    CONF_PRICES_TIMEZONE,
    CONF_PUBLIC_PRICE_RESOLUTION,
    DATA_ELECTRICITY,
    DATA_GAS,
    DATA_MONTH_SUMMARY,
    DATA_INVOICES,
    PRICES_TIMEZONE_HOME_ASSISTANT,
    PRICES_TIMEZONE_UTC,
    PUBLIC_PRICE_RESOLUTION_PT60M,
)

LOGGER = logging.getLogger(__name__)

# Default polling interval. Frank Energie publishes tomorrow's electricity
# prices around 13:00 Europe/Amsterdam; see _next_update_interval() below for
# the faster interval used while waiting for them.
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=60)
FAST_UPDATE_INTERVAL = timedelta(minutes=15)


class FrankEnergieData(TypedDict):
    DATA_ELECTRICITY: PriceData
    DATA_GAS: PriceData
    DATA_MONTH_SUMMARY: MonthSummary | None
    DATA_INVOICES: Invoices | None


def _next_update_interval(now_amsterdam: datetime, has_tomorrow_electricity: bool) -> timedelta:
    """Decide the update interval for the next refresh cycle.

    Tomorrow's electricity prices are usually published around 13:00
    Europe/Amsterdam. From 12:00 onwards, poll every 15 minutes until they
    show up, so they arrive up to 45 minutes sooner than the default hourly
    interval would allow. Before 12:00, or once tomorrow's electricity
    prices are present, the default 60-minute interval applies. A missing
    gas price alone does not trigger the faster polling.
    """
    if now_amsterdam.hour >= 12 and not has_tomorrow_electricity:
        return FAST_UPDATE_INTERVAL
    return DEFAULT_UPDATE_INTERVAL


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
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )

    async def _async_update_data(self) -> FrankEnergieData:
        """Get the latest data from Frank Energie."""
        if dt_util.utcnow().hour == 0 and self._has_usable_data():
            # The Frank Energie API has a daily maintenance window between
            # 00:00 and 01:00 UTC; skip the API call while cached data is
            # still usable, and serve it as is instead.
            LOGGER.debug("Skipping update during the Frank Energie maintenance window (00:00-01:00 UTC)")
            return self.data

        LOGGER.debug("Fetching Frank Energie data")

        # Prices are published per Frank Energie's market day, which is fixed
        # to Europe/Amsterdam regardless of the HA instance's own timezone.
        now_amsterdam = dt_util.now(dt_util.get_time_zone("Europe/Amsterdam"))
        today = now_amsterdam.date()

        try:
            try:
                result = await self._fetch_all(today)
            except (AuthException, AuthRequiredException) as ex:
                result = await self._handle_auth_error(ex, today)
            except (RequestException, FrankEnergieException, ValueError) as ex:
                result = self._handle_update_error(ex)
        finally:
            # Tokens can be renewed transparently inside _query() during any of
            # the awaited calls above, including ones that ultimately raised.
            # Persist them here so a renewed token is never lost when the
            # update otherwise fails later in the same cycle. Idempotent: see
            # _async_persist_tokens().
            if self.api.is_authenticated:
                self._async_persist_tokens()

        # On success or a served stale-data fallback (both reach here without
        # raising), poll faster while tomorrow's electricity prices are still
        # missing after noon; see _next_update_interval().
        self.update_interval = _next_update_interval(now_amsterdam, bool(result[DATA_ELECTRICITY].tomorrow))
        return result

    async def _fetch_all(self, today: date) -> FrankEnergieData:
        """Fetch today's and tomorrow's prices, month summary and invoices, and merge them."""
        prices_today = await self._fetch_prices_with_fallback(today)

        try:
            prices_tomorrow = await self._fetch_prices_with_fallback(today + timedelta(days=1))
        except NoMarketPricesAvailableException as ex:
            LOGGER.debug("No market prices available for tomorrow yet: %s", ex)
            prices_tomorrow = None

        data_month_summary = await self._fetch_optional(
            DATA_MONTH_SUMMARY, lambda: self.api.month_summary(self.site_reference)
        )
        data_invoices = await self._fetch_optional(DATA_INVOICES, lambda: self.api.invoices(self.site_reference))

        tomorrow_electricity = prices_tomorrow.electricity if prices_tomorrow else None
        tomorrow_gas = prices_tomorrow.gas if prices_tomorrow else None

        return {
            DATA_ELECTRICITY: self._merge(prices_today.electricity, tomorrow_electricity),
            DATA_GAS: self._merge(prices_today.gas, tomorrow_gas),
            DATA_MONTH_SUMMARY: data_month_summary,
            DATA_INVOICES: data_invoices,
        }

    async def _fetch_optional(self, key: str, fetch: Callable[[], Awaitable[Any]]) -> Any:
        """Fetch optional account data; on a non-auth failure keep the previous value (or None).

        Auth errors and "user-error:" request errors propagate to the normal handling.
        """
        if not self.api.is_authenticated:
            return None
        try:
            return await fetch()
        except (AuthException, AuthRequiredException):
            raise
        except (FrankEnergieException, ValueError) as ex:
            if isinstance(ex, RequestException) and str(ex).startswith("user-error:"):
                raise
            LOGGER.warning("Could not fetch %s, keeping the previous value: %s", key, ex)
            return self.data.get(key) if self.data else None

    async def _handle_auth_error(self, ex: Exception, today: date) -> FrankEnergieData:
        """Handle an auth error from the first fetch attempt: renew the token and retry once.

        If the renewal succeeds, _fetch_all() is retried exactly once. Any
        error from that retry is classified the same way as the first
        attempt's, except that an auth error on the retry does not trigger
        another renewal; it goes straight to stale-data-or-raise so there is
        at most one renewal and one retry per update.
        """
        LOGGER.debug("Authentication tokens expired, trying to renew them (%s)", ex)

        if not await self._try_renew_token():
            # Renewal failed for a non-auth reason (network/5xx): serve stale
            # data or raise UpdateFailed; the next cycle retries.
            return self._stale_data_or_raise(ex)

        try:
            return await self._fetch_all(today)
        except (AuthException, AuthRequiredException) as retry_ex:
            return self._stale_data_or_raise(retry_ex)
        except (RequestException, FrankEnergieException, ValueError) as retry_ex:
            return self._handle_update_error(retry_ex)

    def _handle_update_error(self, ex: Exception) -> FrankEnergieData:
        """Classify a non-auth update error: report a user error, or fall back to stale data.

        A RequestException whose message starts with "user-error:" indicates
        the account/site itself needs reauth (e.g. after a site_reference from
        a different account). Any other RequestException, plain
        FrankEnergieException (e.g. from a 500 response) or ValueError (e.g.
        from library parsing/an invalid site_reference) should not crash the
        update; fall back to stale data if we have any usable data cached.
        """
        if isinstance(ex, RequestException) and str(ex).startswith("user-error:"):
            raise ConfigEntryAuthFailed from ex

        return self._stale_data_or_raise(ex)

    def _async_persist_tokens(self) -> None:
        """Persist tokens that the library renewed internally back into the config entry.

        python_frank_energie can silently renew the access/refresh tokens inside
        _query() when they are near expiry, updating only `api._auth` in memory.
        The library exposes no public getter for the current tokens (the `auth`
        property exists but logs a deprecation error on every access), so we
        read the private `_auth` attribute here instead.
        """
        # Reading the private `_auth` attribute depends on the pinned
        # python_frank_energie version (see manifest.json); re-check this if
        # that dependency is ever bumped.
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

    def _has_usable_data(self) -> bool:
        """Return whether self.data is set and has usable (non-empty) upcoming electricity and gas prices."""
        return (
            self.data is not None
            and bool(self.data[DATA_ELECTRICITY].upcoming_prices)
            and bool(self.data[DATA_GAS].upcoming_prices)
        )

    def _stale_data_or_raise(self, ex: Exception) -> FrankEnergieData:
        """Return the last known data if it is still usable, otherwise raise UpdateFailed."""
        err = UpdateFailed(ex)

        if self._has_usable_data():
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

    @property
    def prices_timezone(self) -> str:
        """Return the effective prices_timezone option ("home_assistant" or "utc").

        Entries created since this option was introduced default to
        "home_assistant" at creation time. Existing entries without the
        option (pre-dating this feature) are treated as "utc" here, so they
        keep their historical UTC notation unless the user opts in.
        """
        return self.entry.options.get(CONF_PRICES_TIMEZONE, PRICES_TIMEZONE_UTC)

    @property
    def prices_tzinfo(self) -> tzinfo:
        """Return the tzinfo to localize price times with, per the prices_timezone option.

        Uses Home Assistant's own cached default time zone for
        "home_assistant" (set once via hass.config.async_set_time_zone(), so
        this never does blocking I/O when called from the event loop) and the
        UTC singleton for "utc".
        """
        if self.prices_timezone == PRICES_TIMEZONE_HOME_ASSISTANT:
            return dt_util.get_default_time_zone()
        return dt_util.UTC

    @property
    def user_country(self) -> str | None:
        """Return the authenticated user's cached country code, if known."""
        return self._user_country

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
            if self.entry.options.get(CONF_PUBLIC_PRICE_RESOLUTION) == PUBLIC_PRICE_RESOLUTION_PT60M:
                return await self.api.prices(start_date, resolution="PT60M")
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

        # Merges only ever happen within one segment across days (today vs.
        # tomorrow), never between electricity and gas, so there is no need to
        # match the public fallback's resolution to the *other* segment here.
        # Gas can also be PT60M or even daily, which is not a valid
        # PriceResolution to request electricity at (or vice versa). Always
        # request the public fallback at the default "PT15M"; the _merge()
        # ValueError guard handles any cross-day resolution mismatches.
        public_prices = await self._fetch_public_prices(user_country, start_date, "PT15M")

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

    async def _try_renew_token(self) -> bool:
        """Attempt to renew the access token. Returns True on success, False on non-auth failure."""
        try:
            await self.api.renew_token()
            # renew_token() updates api._auth internally; persist it via the
            # same helper used for tokens renewed transparently inside _query(),
            # which preserves the rest of the entry's data (site_reference,
            # username, ...).
            self._async_persist_tokens()

            LOGGER.debug("Successfully renewed token")
            return True

        except (AuthException, AuthRequiredException) as ex:
            LOGGER.error("Failed to renew token: %s. Starting user reauth flow", ex)
            raise ConfigEntryAuthFailed from ex

        except FrankEnergieException as ex:
            # NetworkError, RequestException or a plain FrankEnergieException:
            # renewal failed for a non-auth reason. Log the message only
            # (never tokens) and return False so the caller continues into
            # _stale_data_or_raise(), which either serves stale data or raises
            # UpdateFailed so the next update cycle retries.
            LOGGER.debug("Failed to renew token: %s", ex)
            return False
