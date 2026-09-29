"""Coordinator for daily and monthly usage and costs (see const.SENSOR_GROUP_DAILY_USAGE/MONTHLY_USAGE)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from python_frank_energie.exceptions import AuthException, AuthRequiredException, FrankEnergieException
from python_frank_energie.models import MonthInsights, PeriodUsageAndCosts

from .const import SENSOR_GROUP_DAILY_USAGE, SENSOR_GROUP_MONTHLY_USAGE
from .coordinator import FrankEnergieCoordinator

LOGGER = logging.getLogger(__name__)


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

        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name="Frank Energie usage",
            update_interval=timedelta(hours=3),
        )

    async def _async_update_data(self) -> UsageData:
        """Fetch yesterday's usage/costs and this month's insights, for the enabled groups only."""
        # Usage/costs are published per Frank Energie's market day, fixed to
        # Europe/Amsterdam regardless of the HA instance's own timezone (see
        # FrankEnergieCoordinator._async_update_data).
        today = dt_util.now(dt_util.get_time_zone("Europe/Amsterdam")).date()
        yesterday = today - timedelta(days=1)
        api = self.price_coordinator.api
        site_reference = self.price_coordinator.site_reference

        try:
            daily = (
                await api.period_usage_and_costs(site_reference, yesterday.isoformat())
                if self._daily_enabled
                else None
            )
            monthly = (
                await api.month_insights(site_reference, today.strftime("%Y-%m")) if self._monthly_enabled else None
            )
        except (AuthException, AuthRequiredException) as ex:
            # Reauth is handled by the main coordinator's own update cycle;
            # this coordinator only reports the failure so the next update
            # cycle (after the main coordinator has renewed the token) retries.
            raise UpdateFailed(ex) from ex
        except (FrankEnergieException, ValueError) as ex:
            if self.data is not None:
                LOGGER.warning("Could not update usage and costs, using previous data: %s", ex)
                return self.data
            raise UpdateFailed(ex) from ex

        return UsageData(daily=daily, daily_date=yesterday, monthly=monthly)
