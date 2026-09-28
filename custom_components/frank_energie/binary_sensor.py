"""Frank Energie electricity price analysis binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, CONF_PRICE_ANALYSIS, DOMAIN, ICON, PRICE_LEVEL_CHEAP, PRICE_LEVEL_CHEAP_SOLAR
from .device import device_info
from .price_analysis import AnalysisResult, PriceAnalysisCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frank Energie binary sensor entries."""
    price_analysis_coordinator = hass.data[DOMAIN][config_entry.entry_id][CONF_PRICE_ANALYSIS]

    async_add_entities(
        [
            CheapPriceNowBinarySensor(price_analysis_coordinator, config_entry),
            CheapestPeriodNowBinarySensor(price_analysis_coordinator, config_entry),
        ],
        True,
    )


class FrankEnergiePriceAnalysisBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Base class for the price analysis binary sensors backed by PriceAnalysisCoordinator."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = ICON
    coordinator: PriceAnalysisCoordinator

    def __init__(self, coordinator: PriceAnalysisCoordinator, key: str, name: str, entry: ConfigEntry) -> None:
        """Initialize the price analysis binary sensor."""
        self._attr_unique_id = f"{entry.unique_id}.{key}"
        self._attr_name = name
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
        super().__init__(coordinator, "cheap_price_now", "Cheap electricity price now", entry)

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
        super().__init__(coordinator, "cheapest_period_now", "Cheapest electricity period now", entry)

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
