"""Coordinator for daily and monthly usage and costs (see const.SENSOR_GROUP_DAILY_USAGE/MONTHLY_USAGE)."""
from __future__ import annotations

import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from python_frank_energie.exceptions import AuthException, AuthRequiredException, FrankEnergieException
from python_frank_energie.models import MonthInsights, PeriodUsageAndCosts

from .const import SENSOR_GROUP_DAILY_USAGE, SENSOR_GROUP_MONTHLY_USAGE
from .coordinator import FrankEnergieCoordinator

LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(hours=3)
RETRY_INTERVAL = timedelta(hours=1)


def usage_day_incomplete(data: PeriodUsageAndCosts | None) -> bool:
    """Return True when a day's electricity or gas data is not (completely) published yet.

    A category that is None means the site does not have it and is ignored; feed-in is not considered.
    """
    if data is None:
        return True
    categories = [category for category in (data.electricity, data.gas) if category is not None]
    if not any(category.items for category in categories):
        return True
    return any(not category.items or category.costs_total is None for category in categories)


@dataclass(frozen=True)
class UsageData:
    """Cached usage-and-costs data: yesterday's daily totals and this month's insights."""

    daily: PeriodUsageAndCosts | None
    daily_date: date | None
    monthly: MonthInsights | None


class UsageCoordinator(DataUpdateCoordinator[UsageData]):
    """Fetches yesterday's usage/costs and this month's insights for one config entry.

    Reuses the main FrankEnergieCoordinator's api client and site_reference,
    so token renewal and persistence stay with the main coordinator; auth
    errors here are left for the main coordinator's own update cycle to
    handle (see _async_update_data below).
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, price_coordinator: FrankEnergieCoordinator, groups: set[str]
    ) -> None:
        """Initialize the usage coordinator."""
        self.entry = entry
        self.price_coordinator = price_coordinator
        self._daily_enabled = SENSOR_GROUP_DAILY_USAGE in groups
        self._monthly_enabled = SENSOR_GROUP_MONTHLY_USAGE in groups
        # The month ("YYYY-MM") of the last successfully fetched monthly data, so a
        # failed fetch never shows last month's data as this month's.
        self._monthly_period: str | None = None

        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name="Frank Energie usage",
            update_interval=UPDATE_INTERVAL,
        )

    @staticmethod
    async def _fetch_part(label: str, request: Awaitable[Any], previous: Any) -> tuple[Any, bool]:
        """Await one request; on a non-auth failure warn and return (previous value, False)."""
        try:
            return await request, True
        except (AuthException, AuthRequiredException):
            raise
        except (FrankEnergieException, ValueError) as ex:
            LOGGER.warning("Could not update %s usage and costs, using previous data: %s", label, ex)
            return previous, False

    async def _async_update_data(self) -> UsageData:
        """Fetch yesterday's usage/costs and this month's insights, for the enabled groups only."""
        # Usage/costs are published per Frank Energie's market day, fixed to
        # Europe/Amsterdam regardless of the HA instance's own timezone (see
        # FrankEnergieCoordinator._async_update_data).
        today = dt_util.now(dt_util.get_time_zone("Europe/Amsterdam")).date()
        yesterday = today - timedelta(days=1)
        api = self.price_coordinator.api
        site_reference = self.price_coordinator.site_reference

        previous = self.data
        daily, daily_date, monthly = None, yesterday, None
        failures = 0

        try:
            try:
                if self._daily_enabled:
                    daily, ok = await self._fetch_part(
                        "daily", api.period_usage_and_costs(site_reference, yesterday.isoformat()),
                        previous.daily if previous else None,
                    )
                    if not ok:
                        failures += 1
                        daily_date = previous.daily_date if previous else None
                if self._monthly_enabled:
                    period = today.strftime("%Y-%m")
                    monthly, ok = await self._fetch_part(
                        "monthly", api.month_insights(site_reference, period),
                        previous.monthly if previous and self._monthly_period == period else None,
                    )
                    if ok:
                        self._monthly_period = period
                    failures += not ok
            except (AuthException, AuthRequiredException) as ex:
                # The library wraps exceptions raised while querying (e.g. an
                # expired access token) into FrankEnergieException, so in
                # practice only the pre-query AuthRequiredException (raised
                # when api.is_authenticated is False) can reach this branch;
                # expired credentials take the stale-data path below instead.
                # Reauth itself is handled by the main coordinator's own
                # update cycle, not here.
                raise UpdateFailed(ex) from ex
            if previous is None and failures == self._daily_enabled + self._monthly_enabled:
                raise UpdateFailed("Could not fetch usage and costs")
        finally:
            # Tokens can be renewed transparently inside _query() during any
            # of the awaited calls above, including ones that ultimately
            # raised. Persist them via the price coordinator's own helper so
            # a renewed token is never lost. Idempotent: see
            # FrankEnergieCoordinator._async_persist_tokens().
            if api.is_authenticated:
                self.price_coordinator._async_persist_tokens()

        if self._daily_enabled:
            # A failed daily fetch keeps the previous day's date, so it counts as incomplete too.
            incomplete = daily_date != yesterday or usage_day_incomplete(daily)
            self.update_interval = RETRY_INTERVAL if incomplete else UPDATE_INTERVAL
        return UsageData(daily=daily, daily_date=daily_date, monthly=monthly)
