"""Frank Energie current electricity and gas price information service."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import tzinfo
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CURRENCY_EURO,
    UnitOfEnergy,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from python_frank_energie.models import Price, PriceData

from .analysis import ClassifiedSlot, Window
from .const import (
    ATTR_TIME,
    ATTRIBUTION,
    CONF_COORDINATOR,
    CONF_PRICE_ANALYSIS,
    DATA_ELECTRICITY,
    DATA_GAS,
    DATA_INVOICES,
    DATA_MONTH_SUMMARY,
    DOMAIN,
    ICON,
    PRICE_LEVELS,
    SERVICE_NAME_PRICES,
    SERVICE_NAME_COSTS,
)
from .coordinator import FrankEnergieCoordinator
from .device import device_info
from .price_analysis import AnalysisResult, DayAnalysis, PriceAnalysisCoordinator

_LOGGER = logging.getLogger(__name__)

# Errors raised by value_fn/attr_fn lambdas when the underlying coordinator
# data is legitimately absent/empty (e.g. no price data yet). Legitimately
# absent month_summary()/invoices data is guarded explicitly in the relevant
# lambdas below instead of being caught here, so AttributeError is *not*
# included: a renamed/removed library field should surface as a real error
# instead of silently showing the entity as "unavailable".
_NO_DATA_ERRORS = (TypeError, IndexError, ValueError)


def _price_attr(price, name: str) -> StateType:
    """Return `getattr(price, name)`, or None when `price` itself is None.

    `PriceData.current_hour`, `today_min` and `today_max` return None when no
    slot matches (e.g. empty PriceData, or no current slot just after
    midnight). Guard that explicitly instead of letting the lambdas raise
    AttributeError, which is intentionally not caught by `_NO_DATA_ERRORS`.
    """
    if price is None:
        return None
    return getattr(price, name)


def _tz_name(tz: tzinfo) -> str:
    """Return the IANA zone name for `tz`, for PriceData.asdict(timezone=...).

    ZoneInfo instances (e.g. Home Assistant's configured time zone) expose a
    `.key`; the UTC singleton (datetime.timezone.utc) does not, so fall back
    to the literal "UTC" in that case.
    """
    return getattr(tz, "key", "UTC")


def _next_price(price_data: PriceData) -> Price | None:
    """Return the first price slot of `price_data` that starts after now.

    `PriceData.next_quarter_hour` (now + 15 minutes) is wrong for 60-minute
    slots: it can point at the current slot for up to 45 minutes. `price_data`
    is sorted, so the first slot with `date_from` after now is always the
    correct next slot, regardless of the resolution.
    """
    now = dt_util.utcnow()
    return next((price for price in price_data.price_data if price.date_from > now), None)


@dataclass
class FrankEnergieEntityDescription(SensorEntityDescription):
    """Describes Frank Energie sensor entity."""

    authenticated: bool = False
    service_name: str | None = SERVICE_NAME_PRICES
    value_fn: Callable[[dict], StateType] = None
    attr_fn: Callable[[dict, tzinfo], dict[str, StateType | list]] = lambda _data, _tz: {}


SENSOR_TYPES: tuple[FrankEnergieEntityDescription, ...] = (
    FrankEnergieEntityDescription(
        key="elec_markup",
        name="Current electricity price (All-in)",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "total"),
        attr_fn=lambda data, tz: {"prices": data[DATA_ELECTRICITY].asdict("total", timezone=_tz_name(tz))},
    ),
    FrankEnergieEntityDescription(
        key="elec_market",
        name="Current electricity market price",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "market_price"),
        attr_fn=lambda data, tz: {"prices": data[DATA_ELECTRICITY].asdict("market_price", timezone=_tz_name(tz))},
    ),
    FrankEnergieEntityDescription(
        key="elec_tax",
        name="Current electricity price including tax",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "market_price_with_tax"),
        attr_fn=lambda data, tz: {
            "prices": data[DATA_ELECTRICITY].asdict("market_price_with_tax", timezone=_tz_name(tz))
        },
    ),
    FrankEnergieEntityDescription(
        key="elec_tax_vat",
        name="Current electricity VAT price",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "market_price_tax"),
        entity_registry_enabled_default=False,
    ),
    FrankEnergieEntityDescription(
        key="elec_sourcing",
        name="Current electricity sourcing markup",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "sourcing_markup_price"),
        entity_registry_enabled_default=False,
    ),
    FrankEnergieEntityDescription(
        key="elec_tax_only",
        name="Current electricity tax only",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "energy_tax_price"),
        entity_registry_enabled_default=False,
    ),
    FrankEnergieEntityDescription(
        key="gas_markup",
        name="Current gas price (All-in)",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "total"),
        attr_fn=lambda data, tz: {"prices": data[DATA_GAS].asdict("total", timezone=_tz_name(tz))},
    ),
    FrankEnergieEntityDescription(
        key="gas_market",
        name="Current gas market price",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "market_price"),
        attr_fn=lambda data, tz: {"prices": data[DATA_GAS].asdict("market_price", timezone=_tz_name(tz))},
    ),
    FrankEnergieEntityDescription(
        key="gas_tax",
        name="Current gas price including tax",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "market_price_with_tax"),
        attr_fn=lambda data, tz: {"prices": data[DATA_GAS].asdict("market_price_with_tax", timezone=_tz_name(tz))},
    ),
    FrankEnergieEntityDescription(
        key="gas_tax_vat",
        name="Current gas VAT price",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "market_price_tax"),
        entity_registry_enabled_default=False,
    ),
    FrankEnergieEntityDescription(
        key="gas_sourcing",
        name="Current gas sourcing price",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "sourcing_markup_price"),
        entity_registry_enabled_default=False,
    ),
    FrankEnergieEntityDescription(
        key="gas_tax_only",
        name="Current gas tax only",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "energy_tax_price"),
        entity_registry_enabled_default=False,
    ),
    FrankEnergieEntityDescription(
        key="gas_min",
        name="Lowest gas price today",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].today_min, "total"),
        attr_fn=lambda data, tz: (
            {ATTR_TIME: data[DATA_GAS].today_min.date_from.astimezone(tz)}
            if data[DATA_GAS].today_min is not None
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="gas_max",
        name="Highest gas price today",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].today_max, "total"),
        attr_fn=lambda data, tz: (
            {ATTR_TIME: data[DATA_GAS].today_max.date_from.astimezone(tz)}
            if data[DATA_GAS].today_max is not None
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="elec_min",
        name="Lowest energy price today",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].today_min, "total"),
        attr_fn=lambda data, tz: (
            {ATTR_TIME: data[DATA_ELECTRICITY].today_min.date_from.astimezone(tz)}
            if data[DATA_ELECTRICITY].today_min is not None
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="elec_max",
        name="Highest energy price today",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].today_max, "total"),
        attr_fn=lambda data, tz: (
            {ATTR_TIME: data[DATA_ELECTRICITY].today_max.date_from.astimezone(tz)}
            if data[DATA_ELECTRICITY].today_max is not None
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="elec_avg",
        name="Average electricity price today",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data[DATA_ELECTRICITY].today_avg,
    ),
    FrankEnergieEntityDescription(
        key="elec_next",
        name="Next electricity price (All-in)",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(_next_price(data[DATA_ELECTRICITY]), "total"),
        attr_fn=lambda data, tz: (
            {ATTR_TIME: next_price.date_from.astimezone(tz)}
            if (next_price := _next_price(data[DATA_ELECTRICITY])) is not None
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="elec_tomorrow_avg",
        name="Average electricity price tomorrow",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data[DATA_ELECTRICITY].tomorrow_average_price,
    ),
    FrankEnergieEntityDescription(
        key="elec_tomorrow_min",
        name="Lowest electricity price tomorrow",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].tomorrow_min, "total"),
        attr_fn=lambda data, tz: (
            {ATTR_TIME: data[DATA_ELECTRICITY].tomorrow_min.date_from.astimezone(tz)}
            if data[DATA_ELECTRICITY].tomorrow_min is not None
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="elec_tomorrow_max",
        name="Highest electricity price tomorrow",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].tomorrow_max, "total"),
        attr_fn=lambda data, tz: (
            {ATTR_TIME: data[DATA_ELECTRICITY].tomorrow_max.date_from.astimezone(tz)}
            if data[DATA_ELECTRICITY].tomorrow_max is not None
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="elec_upcoming_min",
        name="Lowest upcoming electricity price",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].upcoming_min, "total"),
        attr_fn=lambda data, tz: (
            {ATTR_TIME: data[DATA_ELECTRICITY].upcoming_min.date_from.astimezone(tz)}
            if data[DATA_ELECTRICITY].upcoming_min is not None
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="elec_upcoming_max",
        name="Highest upcoming electricity price",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].upcoming_max, "total"),
        attr_fn=lambda data, tz: (
            {ATTR_TIME: data[DATA_ELECTRICITY].upcoming_max.date_from.astimezone(tz)}
            if data[DATA_ELECTRICITY].upcoming_max is not None
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="gas_tomorrow_avg",
        name="Average gas price tomorrow",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data[DATA_GAS].tomorrow_average_price,
    ),
    FrankEnergieEntityDescription(
        key="actual_costs_until_last_meter_reading_date",
        name="Actual monthly cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        authenticated=True,
        service_name=SERVICE_NAME_COSTS,
        value_fn=lambda data: (
            data[DATA_MONTH_SUMMARY].actualCostsUntilLastMeterReadingDate
            if data[DATA_MONTH_SUMMARY] is not None
            else None
        ),
        attr_fn=lambda data, tz: (
            {"Last update": data[DATA_MONTH_SUMMARY].lastMeterReadingDate}
            if data[DATA_MONTH_SUMMARY] is not None
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="expected_costs_until_last_meter_reading_date",
        name="Expected monthly cost until now",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        authenticated=True,
        service_name=SERVICE_NAME_COSTS,
        value_fn=lambda data: (
            data[DATA_MONTH_SUMMARY].expectedCostsUntilLastMeterReadingDate
            if data[DATA_MONTH_SUMMARY] is not None
            else None
        ),
        attr_fn=lambda data, tz: (
            {"Last update": data[DATA_MONTH_SUMMARY].lastMeterReadingDate}
            if data[DATA_MONTH_SUMMARY] is not None
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="expected_costs_this_month",
        name="Expected cost this month",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        authenticated=True,
        service_name=SERVICE_NAME_COSTS,
        value_fn=lambda data: (
            data[DATA_MONTH_SUMMARY].expectedCosts if data[DATA_MONTH_SUMMARY] is not None else None
        ),
    ),
    FrankEnergieEntityDescription(
        key="invoice_previous_period",
        name="Invoice previous period",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        authenticated=True,
        service_name=SERVICE_NAME_COSTS,
        value_fn=lambda data: (
            data[DATA_INVOICES].previous_period_invoice.TotalAmount
            if data[DATA_INVOICES] and data[DATA_INVOICES].previous_period_invoice
            else None
        ),
        attr_fn=lambda data, tz: (
            {
                "Start date": data[DATA_INVOICES].previous_period_invoice.StartDate,
                "Description": data[DATA_INVOICES].previous_period_invoice.PeriodDescription,
            }
            if data[DATA_INVOICES] and data[DATA_INVOICES].previous_period_invoice
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="invoice_current_period",
        name="Invoice current period",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        authenticated=True,
        service_name=SERVICE_NAME_COSTS,
        value_fn=lambda data: (
            data[DATA_INVOICES].current_period_invoice.TotalAmount
            if data[DATA_INVOICES] and data[DATA_INVOICES].current_period_invoice
            else None
        ),
        attr_fn=lambda data, tz: (
            {
                "Start date": data[DATA_INVOICES].current_period_invoice.StartDate,
                "Description": data[DATA_INVOICES].current_period_invoice.PeriodDescription,
            }
            if data[DATA_INVOICES] and data[DATA_INVOICES].current_period_invoice
            else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="invoice_upcoming_period",
        name="Invoice upcoming period",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        authenticated=True,
        service_name=SERVICE_NAME_COSTS,
        value_fn=lambda data: (
            data[DATA_INVOICES].upcoming_period_invoice.TotalAmount
            if data[DATA_INVOICES] and data[DATA_INVOICES].upcoming_period_invoice
            else None
        ),
        attr_fn=lambda data, tz: (
            {
                "Start date": data[DATA_INVOICES].upcoming_period_invoice.StartDate,
                "Description": data[DATA_INVOICES].upcoming_period_invoice.PeriodDescription,
            }
            if data[DATA_INVOICES] and data[DATA_INVOICES].upcoming_period_invoice
            else {}
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frank Energie sensor entries."""
    frank_coordinator = hass.data[DOMAIN][config_entry.entry_id][CONF_COORDINATOR]
    price_analysis_coordinator = hass.data[DOMAIN][config_entry.entry_id][CONF_PRICE_ANALYSIS]

    # Add an entity for each sensor type, when authenticated is True,
    # only add the entity if the user is authenticated
    entities: list[SensorEntity] = [
        FrankEnergieSensor(frank_coordinator, description, config_entry)
        for description in SENSOR_TYPES
        if not description.authenticated or frank_coordinator.api.is_authenticated
    ]
    entities.extend(
        [
            FrankEnergiePriceLevelSensor(price_analysis_coordinator, config_entry),
            FrankEnergiePriceAnalysisDaySensor(price_analysis_coordinator, config_entry, "today"),
            FrankEnergiePriceAnalysisDaySensor(price_analysis_coordinator, config_entry, "tomorrow"),
            FrankEnergieNextCheapestPeriodSensor(price_analysis_coordinator, config_entry),
        ]
    )

    async_add_entities(entities, True)


class FrankEnergieSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Frank Energie sensor."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = ICON
    # The "prices" attribute holds up to 192+ quarter-hour price slots (~17 KB
    # once serialized), over the recorder's 16 KB attribute size limit, so
    # exclude it from being recorded to avoid it being dropped/warned about.
    _unrecorded_attributes = frozenset({"prices"})

    def __init__(
        self,
        coordinator: FrankEnergieCoordinator,
        description: FrankEnergieEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description: FrankEnergieEntityDescription = description
        self._attr_unique_id = f"{entry.unique_id}.{description.key}"
        self._attr_device_info = device_info(entry, description.service_name)

        super().__init__(coordinator)

    def _compute_native_value(self) -> StateType:
        """Compute the native value from the entity description's value_fn."""
        try:
            return self.entity_description.value_fn(self.coordinator.data)
        except _NO_DATA_ERRORS:
            # No data available
            return None

    async def async_update(self) -> None:
        """Get the latest data and updates the states."""
        self._attr_native_value = self._compute_native_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Recompute the native value so new coordinator data shows up immediately."""
        self._attr_native_value = self._compute_native_value()
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        """Register the quarter-hourly state refresh once the entity is added to hass."""
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
        self.async_schedule_update_ha_state(True)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        try:
            return self.entity_description.attr_fn(self.coordinator.data, self.coordinator.prices_tzinfo)
        except _NO_DATA_ERRORS:
            return {}

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None


def _round_price(value: float | None) -> float | None:
    """Round a price to 5 decimals, for price analysis attributes."""
    return round(value, 5) if value is not None else None


def _round_kwh(value: float | None) -> float | None:
    """Round a kWh value to 3 decimals, for price analysis attributes."""
    return round(value, 3) if value is not None else None


def _serialize_window(window: Window, tz: tzinfo) -> dict[str, Any]:
    """Serialize a `Window` for a price analysis attribute (start/end localized to `tz`)."""
    data: dict[str, Any] = {
        "start": window.start.astimezone(tz),
        "end": window.end.astimezone(tz),
        "average_price": _round_price(window.average_price),
        "minutes": window.minutes,
    }
    if window.average_solar_kwh is not None:
        data["average_solar_kwh"] = _round_kwh(window.average_solar_kwh)
    return data


def _serialize_slot(slot: ClassifiedSlot, tz: tzinfo, cheapest_period: Window | None, now) -> dict[str, Any]:
    """Serialize a single `ClassifiedSlot` for the "slots" price analysis attribute."""
    in_cheapest_period = cheapest_period is not None and cheapest_period.start <= slot.date_from < cheapest_period.end
    return {
        "from": slot.date_from.astimezone(tz),
        "till": slot.date_till.astimezone(tz),
        "price": _round_price(slot.price),
        "level": slot.level,
        "solar_kwh": _round_kwh(slot.solar_kwh),
        "in_cheapest_period": in_cheapest_period,
        "is_current": slot.date_from <= now < slot.date_till,
    }


def _day_analysis_attributes(day: DayAnalysis, tz: tzinfo, thresholds: dict[str, StateType]) -> dict[str, Any]:
    """Build the extra_state_attributes for a price_analysis_today/tomorrow sensor."""
    now = dt_util.utcnow()
    return {
        "slots": [_serialize_slot(slot, tz, day.cheapest_period, now) for slot in day.slots],
        "cheapest_period": _serialize_window(day.cheapest_period, tz) if day.cheapest_period is not None else None,
        "cheap_windows": [_serialize_window(window, tz) for window in day.cheap_windows],
        "expensive_windows": [_serialize_window(window, tz) for window in day.expensive_windows],
        "solar_windows": [_serialize_window(window, tz) for window in day.solar_windows],
        "thresholds": thresholds,
    }


class FrankEnergiePriceAnalysisEntity(CoordinatorEntity, SensorEntity):
    """Base class for the electricity price analysis sensors backed by PriceAnalysisCoordinator."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = ICON
    coordinator: PriceAnalysisCoordinator

    def __init__(self, coordinator: PriceAnalysisCoordinator, key: str, name: str, entry: ConfigEntry) -> None:
        """Initialize the price analysis entity."""
        self._attr_unique_id = f"{entry.unique_id}.{key}"
        self._attr_name = name
        self._attr_device_info = device_info(entry, SERVICE_NAME_PRICES)
        super().__init__(coordinator)

    @property
    def _result(self) -> AnalysisResult | None:
        """Return the cached analysis result, or None when there is no data yet."""
        return self.coordinator.data

    @property
    def available(self) -> bool:
        """Unavailable when there is no analysis result, or this entity's native value is None."""
        return super().available and self.native_value is not None


class FrankEnergiePriceLevelSensor(FrankEnergiePriceAnalysisEntity):
    """The current electricity price level (cheap_solar/cheap/normal/expensive)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(PRICE_LEVELS)
    _attr_translation_key = "price_level"

    def __init__(self, coordinator: PriceAnalysisCoordinator, entry: ConfigEntry) -> None:
        """Initialize the price level sensor."""
        super().__init__(coordinator, "price_level", "Electricity price level", entry)

    @property
    def native_value(self) -> StateType:
        result = self._result
        return result.current_level if result is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self._result
        if result is None:
            return {}
        return {
            "cheap_threshold": _round_price(result.cheap_threshold),
            "expensive_threshold": _round_price(result.expensive_threshold),
        }


class FrankEnergiePriceAnalysisDaySensor(FrankEnergiePriceAnalysisEntity):
    """Electricity price analysis (levels, windows, cheapest period) for today or tomorrow."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _unrecorded_attributes = frozenset(
        {"slots", "cheapest_period", "cheap_windows", "expensive_windows", "solar_windows", "thresholds"}
    )

    def __init__(self, coordinator: PriceAnalysisCoordinator, entry: ConfigEntry, period: str) -> None:
        """Initialize the price analysis sensor for `period` ("today" or "tomorrow")."""
        self._period = period
        key = f"price_analysis_{period}"
        name = f"Electricity price analysis {period}"
        super().__init__(coordinator, key, name, entry)

    def _day(self) -> DayAnalysis | None:
        """Return this sensor's DayAnalysis (today's or tomorrow's), or None when unavailable."""
        result = self._result
        if result is None:
            return None
        return result.today if self._period == "today" else result.tomorrow

    @property
    def native_value(self) -> StateType:
        day = self._day()
        if day is None or day.cheapest_period is None:
            return None
        return day.cheapest_period.start

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        day = self._day()
        result = self._result
        if day is None or result is None:
            return {}
        thresholds = {
            "cheap": _round_price(result.cheap_threshold),
            "expensive": _round_price(result.expensive_threshold),
            "solar_kwh": _round_kwh(result.solar_threshold_kwh),
        }
        return _day_analysis_attributes(day, self.coordinator.price_coordinator.prices_tzinfo, thresholds)


class FrankEnergieNextCheapestPeriodSensor(FrankEnergiePriceAnalysisEntity):
    """The next upcoming cheapest electricity period, starting from now.

    While `now` is inside the reported window, it is kept stable (the same
    start/end) across refreshes instead of shrinking/drifting forward every
    quarter hour as already-elapsed slots would otherwise drop out of the
    search; see `PriceAnalysisCoordinator._next_cheapest_period`.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: PriceAnalysisCoordinator, entry: ConfigEntry) -> None:
        """Initialize the next cheapest period sensor."""
        super().__init__(coordinator, "next_cheapest_period", "Next cheapest electricity period", entry)

    def _window(self) -> Window | None:
        result = self._result
        return result.next_cheapest_period if result is not None else None

    @property
    def native_value(self) -> StateType:
        window = self._window()
        return window.start if window is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        window = self._window()
        if window is None:
            return {}
        tz = self.coordinator.price_coordinator.prices_tzinfo
        return {
            "end": window.end.astimezone(tz),
            "average_price": _round_price(window.average_price),
            "minutes": window.minutes,
        }
