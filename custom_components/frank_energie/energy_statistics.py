"""Imports Frank Energie's hourly usage and costs as external statistics for the Energy dashboard."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify
from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter
from python_frank_energie.exceptions import AuthException, AuthRequiredException, FrankEnergieException
from python_frank_energie.models import PeriodUsageAndCosts

from .const import DOMAIN
from .coordinator import FrankEnergieCoordinator

LOGGER = logging.getLogger(__name__)

FIRST_RUN_DAYS = 30
SUM_LOOKBACK = timedelta(days=31)

# (kind, readable name, category attribute, UsageItem field, unit, unit class)
STATISTICS = (
    ("electricity_usage", "Electricity usage", "electricity", "usage",
     UnitOfEnergy.KILO_WATT_HOUR, EnergyConverter.UNIT_CLASS),
    ("electricity_costs", "Electricity costs", "electricity", "costs", CURRENCY_EURO, None),
    ("feed_in", "Feed-in", "feed_in", "usage", UnitOfEnergy.KILO_WATT_HOUR, EnergyConverter.UNIT_CLASS),
    ("feed_in_revenue", "Feed-in revenue", "feed_in", "costs", CURRENCY_EURO, None),
    ("gas_usage", "Gas usage", "gas", "usage", UnitOfVolume.CUBIC_METERS, VolumeConverter.UNIT_CLASS),
    ("gas_costs", "Gas costs", "gas", "costs", CURRENCY_EURO, None),
)


class FrankEnergieStatisticsImporter:
    """Imports hourly usage and costs of the last days as long-term statistics (API errors are logged, not raised)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, price_coordinator: FrankEnergieCoordinator) -> None:
        """Initialize the importer."""
        self.hass = hass
        self.entry = entry
        self.price_coordinator = price_coordinator
        self._lock = asyncio.Lock()
        self._warned_no_recorder = False

    def _statistic_id(self, kind: str) -> str:
        return f"{DOMAIN}:{kind}_{slugify(self.price_coordinator.site_reference)}"

    async def async_import(self, _now: datetime | None = None) -> None:
        """Fetch the missing days and import them; API errors are logged, not raised."""
        if self._lock.locked():
            return
        async with self._lock:
            if dt_util.utcnow().hour == 0:
                # The Frank Energie API has a daily maintenance window between 00:00 and 01:00 UTC.
                LOGGER.debug("Skipping the statistics import during the Frank Energie maintenance window")
                return
            if "recorder" not in self.hass.config.components:
                if not self._warned_no_recorder:
                    LOGGER.warning("The recorder is not loaded, not importing Energy dashboard statistics")
                    self._warned_no_recorder = True
                return
            api = self.price_coordinator.api
            try:
                days = await self._fetch_days(await self._days_to_import())
            finally:
                # Tokens may be renewed during any call above; see FrankEnergieCoordinator._async_persist_tokens().
                if api.is_authenticated:
                    self.price_coordinator._async_persist_tokens()
            if days:
                for statistic in STATISTICS:
                    await self._import_statistic(days, *statistic)

    async def _days_to_import(self) -> list[date]:
        """Amsterdam dates to fetch: 30 days on the first run, else the last stored day and the day before."""
        yesterday = dt_util.now(dt_util.get_time_zone("Europe/Amsterdam")).date() - timedelta(days=1)
        last = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, self._statistic_id("electricity_usage"), True, {"start"}
        )
        rows = last.get(self._statistic_id("electricity_usage"))
        if not rows:
            start = yesterday - timedelta(days=FIRST_RUN_DAYS - 1)
        else:
            last_date = dt_util.utc_from_timestamp(rows[0]["start"]).astimezone(
                dt_util.get_time_zone("Europe/Amsterdam")
            ).date()
            start = min(last_date, yesterday) - timedelta(days=1)
        return [start + timedelta(days=i) for i in range((yesterday - start).days + 1)]

    async def _fetch_days(self, days: list[date]) -> list[PeriodUsageAndCosts]:
        """Fetch the days in order; stop at an API error or at an empty day within the last 2 days.

        Older empty days (e.g. before the customer started) are skipped; the last day is yesterday.
        """
        fetched = []
        for day in days:
            try:
                data = await self.price_coordinator.api.period_usage_and_costs(
                    self.price_coordinator.site_reference, day.isoformat()
                )
            except (FrankEnergieException, ValueError, AuthException, AuthRequiredException) as ex:
                LOGGER.warning("Could not fetch usage and costs for %s, stopping the import: %s", day, ex)
                break
            if data is None or data.electricity is None or not data.electricity.items:
                if day < days[-1] - timedelta(days=1):
                    LOGGER.debug("No usage data for %s, skipping", day)
                    continue
                LOGGER.debug("No usage data for %s yet, stopping", day)
                break
            fetched.append(data)
        return fetched

    @staticmethod
    def _hourly_values(days: list[PeriodUsageAndCosts], category_name: str, field: str) -> dict[datetime, float]:
        """Sum the field of a category's items per UTC hour (so 15-minute items work too)."""
        hourly: dict[datetime, float] = defaultdict(float)
        for day in days:
            category = getattr(day, category_name)
            if category is None:
                continue
            for item in category.items:
                start = dt_util.parse_datetime(item.from_time)
                if start is None:
                    continue
                hour = dt_util.as_utc(start).replace(minute=0, second=0, microsecond=0)
                hourly[hour] += getattr(item, field)
        return hourly

    async def _import_statistic(
        self,
        days: list[PeriodUsageAndCosts],
        kind: str,
        name: str,
        category_name: str,
        field: str,
        unit: str,
        unit_class: str | None,
    ) -> None:
        hourly = self._hourly_values(days, category_name, field)
        if not hourly:
            return
        statistic_id = self._statistic_id(kind)
        first_hour = min(hourly)
        existing = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            first_hour - SUM_LOOKBACK,
            first_hour,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )
        rows = existing.get(statistic_id)
        running_sum = (rows[-1].get("sum") or 0.0) if rows else 0.0
        stats = []
        for hour in sorted(hourly):
            running_sum += hourly[hour]
            stats.append(StatisticData(start=hour, state=hourly[hour], sum=running_sum))
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{self.entry.title} {name}",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class=unit_class,
            unit_of_measurement=unit,
        )
        async_add_external_statistics(self.hass, metadata, stats)
