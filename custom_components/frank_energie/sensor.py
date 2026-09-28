"""Frank Energie current electricity and gas price information service."""
from __future__ import annotations

import logging
from dataclasses import dataclass
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
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_TIME,
    ATTRIBUTION,
    CONF_COORDINATOR,
    DATA_ELECTRICITY,
    DATA_GAS,
    DATA_INVOICES,
    DATA_MONTH_SUMMARY,
    DOMAIN,
    ICON,
    SERVICE_NAME_PRICES,
    SERVICE_NAME_COSTS,
)
from .coordinator import FrankEnergieCoordinator

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


@dataclass
class FrankEnergieEntityDescription(SensorEntityDescription):
    """Describes Frank Energie sensor entity."""

    authenticated: bool = False
    service_name: str | None = SERVICE_NAME_PRICES
    value_fn: Callable[[dict], StateType] = None
    attr_fn: Callable[[dict], dict[str, StateType | list]] = lambda _: {}


SENSOR_TYPES: tuple[FrankEnergieEntityDescription, ...] = (
    FrankEnergieEntityDescription(
        key="elec_markup",
        name="Current electricity price (All-in)",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "total"),
        attr_fn=lambda data: {"prices": data[DATA_ELECTRICITY].asdict("total")},
    ),
    FrankEnergieEntityDescription(
        key="elec_market",
        name="Current electricity market price",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "market_price"),
        attr_fn=lambda data: {"prices": data[DATA_ELECTRICITY].asdict("market_price")},
    ),
    FrankEnergieEntityDescription(
        key="elec_tax",
        name="Current electricity price including tax",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "market_price_with_tax"),
        attr_fn=lambda data: {
            "prices": data[DATA_ELECTRICITY].asdict("market_price_with_tax")
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
        attr_fn=lambda data: {"prices": data[DATA_GAS].asdict("total")},
    ),
    FrankEnergieEntityDescription(
        key="gas_market",
        name="Current gas market price",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "market_price"),
        attr_fn=lambda data: {"prices": data[DATA_GAS].asdict("market_price")},
    ),
    FrankEnergieEntityDescription(
        key="gas_tax",
        name="Current gas price including tax",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "market_price_with_tax"),
        attr_fn=lambda data: {"prices": data[DATA_GAS].asdict("market_price_with_tax")},
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
        attr_fn=lambda data: (
            {ATTR_TIME: data[DATA_GAS].today_min.date_from} if data[DATA_GAS].today_min is not None else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="gas_max",
        name="Highest gas price today",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].today_max, "total"),
        attr_fn=lambda data: (
            {ATTR_TIME: data[DATA_GAS].today_max.date_from} if data[DATA_GAS].today_max is not None else {}
        ),
    ),
    FrankEnergieEntityDescription(
        key="elec_min",
        name="Lowest energy price today",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].today_min, "total"),
        attr_fn=lambda data: (
            {ATTR_TIME: data[DATA_ELECTRICITY].today_min.date_from}
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
        attr_fn=lambda data: (
            {ATTR_TIME: data[DATA_ELECTRICITY].today_max.date_from}
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
        attr_fn=lambda data: (
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
        attr_fn=lambda data: (
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
        attr_fn=lambda data: (
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
        attr_fn=lambda data: (
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
        attr_fn=lambda data: (
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

    # Add an entity for each sensor type, when authenticated is True,
    # only add the entity if the user is authenticated
    async_add_entities(
        [
            FrankEnergieSensor(frank_coordinator, description, config_entry)
            for description in SENSOR_TYPES
            if not description.authenticated or frank_coordinator.api.is_authenticated
        ],
        True,
    )


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

        # Do not set extra identifier for default service, backwards compatibility
        if description.service_name is SERVICE_NAME_PRICES:
            device_info_identifiers = {(DOMAIN, f"{entry.entry_id}")}
        else:
            device_info_identifiers = {(DOMAIN, f"{entry.entry_id}", description.service_name)}

        self._attr_device_info = DeviceInfo(
            identifiers=device_info_identifiers,
            name=f"Frank Energie - {description.service_name}",
            manufacturer="Frank Energie",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.frankenergie.nl/goedkoop",
        )

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
            return self.entity_description.attr_fn(self.coordinator.data)
        except _NO_DATA_ERRORS:
            return {}

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None
