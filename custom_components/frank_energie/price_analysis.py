"""Computes and caches electricity price analysis (levels, windows, cheapest periods).

`PriceAnalysisCoordinator` is a `DataUpdateCoordinator` in its own right (see
the module docstring note below), so the price-analysis entities can be plain
`CoordinatorEntity` subclasses just like the existing price sensors. It is not
polling anything itself though: `update_interval` is `None`, and a refresh is
instead triggered by the price coordinator's own updates and by the same
quarter-hour timer the existing price sensors use for their own scheduled
updates (see `async_setup_listeners`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from python_frank_energie.models import Price

from .analysis import ClassifiedSlot, Window, classify, find_cheapest_period, group_windows, solar_per_slot
from .const import (
    CONF_CHEAP_PRICE_THRESHOLD,
    CONF_CHEAPEST_PERIOD_MINUTES,
    CONF_EXPENSIVE_PRICE_THRESHOLD,
    CONF_SOLAR_FORECAST_ENTRY,
    CONF_SOLAR_THRESHOLD_KWH,
    DATA_ELECTRICITY,
    DEFAULT_CHEAP_PRICE_THRESHOLD,
    DEFAULT_CHEAPEST_PERIOD_MINUTES,
    DEFAULT_EXPENSIVE_PRICE_THRESHOLD,
    DEFAULT_SOLAR_THRESHOLD_KWH,
)
from .coordinator import FrankEnergieCoordinator
from .solar_forecast import async_get_solar_forecast_wh_hours

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DayAnalysis:
    """The price analysis for a single market day (today or tomorrow)."""

    slots: list[ClassifiedSlot]
    cheap_windows: list[Window]
    expensive_windows: list[Window]
    solar_windows: list[Window]
    cheapest_period: Window | None


@dataclass(frozen=True)
class AnalysisResult:
    """A full price-analysis result, as cached by `PriceAnalysisCoordinator`."""

    today: DayAnalysis
    tomorrow: DayAnalysis | None
    next_cheapest_period: Window | None
    current_level: str | None
    cheap_threshold: float
    expensive_threshold: float
    solar_threshold_kwh: float


def _classify_slots(
    slots: list[Price],
    solar_kwh_by_start: dict[datetime, float],
    cheap: float,
    expensive: float,
    solar_threshold: float,
) -> list[ClassifiedSlot]:
    """Classify a list of price slots into `ClassifiedSlot`s."""
    classified = []
    for slot in slots:
        solar_kwh = solar_kwh_by_start.get(slot.date_from, 0.0)
        level = classify(slot.total, cheap, expensive, solar_kwh, solar_threshold)
        classified.append(ClassifiedSlot(slot.date_from, slot.date_till, slot.total, level, solar_kwh))
    return classified


def _build_day_analysis(classified: list[ClassifiedSlot], raw_slots: list[Price], cheapest_minutes: int) -> DayAnalysis:
    """Build a `DayAnalysis` from a day's classified slots."""
    cheap_windows, expensive_windows, solar_windows = group_windows(classified)
    cheapest_period = find_cheapest_period(raw_slots, cheapest_minutes)
    return DayAnalysis(
        slots=classified,
        cheap_windows=cheap_windows,
        expensive_windows=expensive_windows,
        solar_windows=solar_windows,
        cheapest_period=cheapest_period,
    )


def _current_level(slots: list[ClassifiedSlot], now: datetime) -> str | None:
    """Return the level of the slot containing `now`, or None if there isn't one."""
    return next((slot.level for slot in slots if slot.date_from <= now < slot.date_till), None)


class PriceAnalysisCoordinator(DataUpdateCoordinator[AnalysisResult | None]):
    """Computes and caches the electricity price analysis for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, price_coordinator: FrankEnergieCoordinator) -> None:
        """Initialize the price analysis coordinator."""
        self.entry = entry
        self.price_coordinator = price_coordinator

        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name="Frank Energie price analysis",
            update_interval=None,
        )

    def async_setup_listeners(self) -> list[Callable[[], None]]:
        """Register the listeners that trigger a refresh; return their unsub callables."""
        return [
            self.price_coordinator.async_add_listener(self._async_trigger_refresh),
            event.async_track_utc_time_change(
                self.hass, self._async_trigger_refresh, minute=[0, 15, 30, 45], second=0
            ),
        ]

    @callback
    def _async_trigger_refresh(self, *_args) -> None:
        """Trigger an async refresh in response to a coordinator update or the quarter-hour timer.

        Named distinctly from (and must never be named) `_schedule_refresh`:
        that name is used internally by `DataUpdateCoordinator` itself (called
        from `async_add_listener` and after every `_async_refresh()`), and
        overriding it here would recurse into an infinite refresh loop.
        """
        self.hass.async_create_task(self.async_refresh())

    async def _async_update_data(self) -> AnalysisResult | None:
        """Recompute the price analysis from the price coordinator's current data."""
        data = self.price_coordinator.data
        electricity = data.get(DATA_ELECTRICITY) if data else None
        if electricity is None or not electricity.all:
            return None

        options = self.entry.options
        cheap = options.get(CONF_CHEAP_PRICE_THRESHOLD, DEFAULT_CHEAP_PRICE_THRESHOLD)
        expensive = options.get(CONF_EXPENSIVE_PRICE_THRESHOLD, DEFAULT_EXPENSIVE_PRICE_THRESHOLD)
        cheapest_minutes = options.get(CONF_CHEAPEST_PERIOD_MINUTES, DEFAULT_CHEAPEST_PERIOD_MINUTES)
        solar_threshold = options.get(CONF_SOLAR_THRESHOLD_KWH, DEFAULT_SOLAR_THRESHOLD_KWH)
        solar_entry_id = options.get(CONF_SOLAR_FORECAST_ENTRY)

        wh_hours = await async_get_solar_forecast_wh_hours(self.hass, solar_entry_id)
        solar_kwh_by_start = solar_per_slot(electricity.all, wh_hours)

        today_slots = electricity.today
        tomorrow_slots = electricity.tomorrow

        today_classified = _classify_slots(today_slots, solar_kwh_by_start, cheap, expensive, solar_threshold)
        tomorrow_classified = _classify_slots(tomorrow_slots, solar_kwh_by_start, cheap, expensive, solar_threshold)

        today = _build_day_analysis(today_classified, today_slots, cheapest_minutes)
        tomorrow = (
            _build_day_analysis(tomorrow_classified, tomorrow_slots, cheapest_minutes) if tomorrow_slots else None
        )

        now = dt_util.utcnow()
        next_cheapest_period = find_cheapest_period(electricity.all, cheapest_minutes, not_before=now)
        current_level = _current_level(today_classified + tomorrow_classified, now)

        return AnalysisResult(
            today=today,
            tomorrow=tomorrow,
            next_cheapest_period=next_cheapest_period,
            current_level=current_level,
            cheap_threshold=cheap,
            expensive_threshold=expensive,
            solar_threshold_kwh=solar_threshold,
        )
