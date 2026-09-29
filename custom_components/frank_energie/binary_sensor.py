"""Frank Energie electricity price analysis binary sensors."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTRIBUTION,
    DATA_ELECTRICITY,
    ICON,
    PRICE_LEVEL_CHEAP,
    PRICE_LEVEL_CHEAP_SOLAR,
    enabled_groups,
    key_enabled,
)
from .coordinator import FrankEnergieCoordinator
from .device import device_info
from .price_analysis import AnalysisResult, PriceAnalysisCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frank Energie binary sensor entries."""
    runtime_data = config_entry.runtime_data
    price_analysis_coordinator = runtime_data.price_analysis
    groups = enabled_groups(config_entry)

    if key_enabled("tomorrow_prices_available", groups):
        async_add_entities([TomorrowPricesAvailableBinarySensor(runtime_data.coordinator, config_entry)], False)

    # price_analysis_coordinator is None when the price_analysis sensor group
    # is disabled (see __init__.py): no PriceAnalysisCoordinator is created
    # or refreshed in that case, so these entities are skipped entirely.
    #
    # update_before_add=False: these read PriceAnalysisCoordinator.data, which
    # is already populated by the time platforms are set up (see sensor.py's
    # async_setup_entry for the full rationale).
    if price_analysis_coordinator is not None:
        async_add_entities(
            [
                CheapPriceNowBinarySensor(price_analysis_coordinator, config_entry),
                CheapestPeriodNowBinarySensor(price_analysis_coordinator, config_entry),
            ],
            False,
        )


class TomorrowPricesAvailableBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """On when tomorrow's electricity prices have been published.

    Backed by the main FrankEnergieCoordinator (not the price analysis
    coordinator), so it is available for both authenticated and public
    entries. "Tomorrow" matches the coordinator's own definition (see
    FrankEnergieCoordinator._next_update_interval, which uses
    `bool(data[DATA_ELECTRICITY].tomorrow)` the same way).
    """

    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:calendar-clock"
    _attr_has_entity_name = True
    _attr_translation_key = "tomorrow_prices_available"
    coordinator: FrankEnergieCoordinator

    def __init__(self, coordinator: FrankEnergieCoordinator, entry: ConfigEntry) -> None:
        """Initialize the tomorrow prices available binary sensor."""
        self._attr_unique_id = f"{entry.unique_id}.tomorrow_prices_available"
        self._attr_device_info = device_info(entry)
        super().__init__(coordinator)

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None
        return bool(data[DATA_ELECTRICITY].tomorrow)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.is_on:
            return {}
        amsterdam_tomorrow = dt_util.now(dt_util.get_time_zone("Europe/Amsterdam")).date() + timedelta(days=1)
        return {"date": amsterdam_tomorrow.isoformat()}

    async def async_added_to_hass(self) -> None:
        """Register the quarter-hourly refresh, so `is_on` flips off again right after midnight."""
        await super().async_added_to_hass()
        self.async_on_remove(
            event.async_track_utc_time_change(
                self.hass,
                self._handle_scheduled_update,
                minute=[0, 15, 30, 45],
                second=0,
            )
        )

    @callback
    def _handle_scheduled_update(self, _now) -> None:
        """Handle a scheduled update."""
        self.async_write_ha_state()


class FrankEnergiePriceAnalysisBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Base class for the price analysis binary sensors backed by PriceAnalysisCoordinator."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = ICON
    _attr_has_entity_name = True
    coordinator: PriceAnalysisCoordinator

    def __init__(self, coordinator: PriceAnalysisCoordinator, key: str, entry: ConfigEntry) -> None:
        """Initialize the price analysis binary sensor."""
        self._attr_unique_id = f"{entry.unique_id}.{key}"
        self._attr_translation_key = key
        self._attr_device_info = device_info(entry)
        super().__init__(coordinator)

    @property
    def _result(self) -> AnalysisResult | None:
        """Return the cached analysis result, or None when there is no data yet."""
        return self.coordinator.data

    @property
    def available(self) -> bool:
        """Unavailable when there is no analysis result."""
        return super().available and self._result is not None


class CheapPriceNowBinarySensor(FrankEnergiePriceAnalysisBinarySensor):
    """On when the current electricity price is cheap or cheap + solar."""

    def __init__(self, coordinator: PriceAnalysisCoordinator, entry: ConfigEntry) -> None:
        """Initialize the cheap price now binary sensor."""
        super().__init__(coordinator, "cheap_price_now", entry)

    @property
    def is_on(self) -> bool | None:
        result = self._result
        if result is None:
            return None
        return result.current_level in (PRICE_LEVEL_CHEAP, PRICE_LEVEL_CHEAP_SOLAR)


class CheapestPeriodNowBinarySensor(FrankEnergiePriceAnalysisBinarySensor):
    """On while now is within today's cheapest electricity period."""

    def __init__(self, coordinator: PriceAnalysisCoordinator, entry: ConfigEntry) -> None:
        """Initialize the cheapest period now binary sensor."""
        super().__init__(coordinator, "cheapest_period_now", entry)

    @property
    def is_on(self) -> bool | None:
        result = self._result
        if result is None:
            return None
        cheapest_period = result.today.cheapest_period
        if cheapest_period is None:
            return False
        now = dt_util.utcnow()
        return cheapest_period.start <= now < cheapest_period.end
