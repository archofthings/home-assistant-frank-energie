"""Frank Energie current electricity and gas price information service."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, tzinfo
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
from python_frank_energie.models import Difference, EnergyCategory, Price, PriceData

from .analysis import ClassifiedSlot, Window
from .const import (
    ATTR_TIME,
    ATTRIBUTION,
    DATA_ELECTRICITY,
    DATA_GAS,
    DATA_INVOICES,
    DATA_MONTH_SUMMARY,
    ICON,
    PRICE_LEVELS,
    SERVICE_NAME_PRICES,
    SERVICE_NAME_COSTS,
    enabled_groups,
    key_enabled,
)
from .contract import ContractCoordinator
from .coordinator import FrankEnergieCoordinator
from .device import device_info
from .price_analysis import AnalysisResult, DayAnalysis, PriceAnalysisCoordinator
from .usage import UsageCoordinator, UsageData

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


def _yearly_invoices_attrs(data: dict, year: int) -> dict[str, Any]:
    """Build the "invoices" attribute for a costs_this_year/costs_previous_year sensor."""
    if data[DATA_INVOICES] is None:
        return {}
    return {
        "invoices": [
            {
                "start_date": invoice.StartDate.date().isoformat(),
                "description": invoice.PeriodDescription,
                "total_amount": round(invoice.TotalAmount, 2),
            }
            for invoice in data[DATA_INVOICES].get_invoices_for_year(year)
        ]
    }


SENSOR_TYPES: tuple[FrankEnergieEntityDescription, ...] = (
    FrankEnergieEntityDescription(
        key="elec_markup",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "total"),
        attr_fn=lambda data, tz: {"prices": data[DATA_ELECTRICITY].asdict("total", timezone=_tz_name(tz))},
    ),
    FrankEnergieEntityDescription(
        key="elec_market",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "market_price"),
        attr_fn=lambda data, tz: {"prices": data[DATA_ELECTRICITY].asdict("market_price", timezone=_tz_name(tz))},
    ),
    FrankEnergieEntityDescription(
        key="elec_tax",
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
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "market_price_tax"),
        entity_registry_enabled_default=False,
    ),
    FrankEnergieEntityDescription(
        key="elec_sourcing",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "sourcing_markup_price"),
        entity_registry_enabled_default=False,
    ),
    FrankEnergieEntityDescription(
        key="elec_tax_only",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_ELECTRICITY].current_hour, "energy_tax_price"),
        entity_registry_enabled_default=False,
    ),
    FrankEnergieEntityDescription(
        key="gas_markup",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "total"),
        attr_fn=lambda data, tz: {"prices": data[DATA_GAS].asdict("total", timezone=_tz_name(tz))},
    ),
    FrankEnergieEntityDescription(
        key="gas_market",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "market_price"),
        attr_fn=lambda data, tz: {"prices": data[DATA_GAS].asdict("market_price", timezone=_tz_name(tz))},
    ),
    FrankEnergieEntityDescription(
        key="gas_tax",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "market_price_with_tax"),
        attr_fn=lambda data, tz: {"prices": data[DATA_GAS].asdict("market_price_with_tax", timezone=_tz_name(tz))},
    ),
    FrankEnergieEntityDescription(
        key="gas_tax_vat",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "market_price_tax"),
        entity_registry_enabled_default=False,
    ),
    FrankEnergieEntityDescription(
        key="gas_sourcing",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "sourcing_markup_price"),
        entity_registry_enabled_default=False,
    ),
    FrankEnergieEntityDescription(
        key="gas_tax_only",
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _price_attr(data[DATA_GAS].current_hour, "energy_tax_price"),
        entity_registry_enabled_default=False,
    ),
    FrankEnergieEntityDescription(
        key="gas_min",
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
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data[DATA_ELECTRICITY].today_avg,
    ),
    FrankEnergieEntityDescription(
        key="elec_next",
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
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data[DATA_ELECTRICITY].tomorrow_average_price,
    ),
    FrankEnergieEntityDescription(
        key="elec_tomorrow_min",
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
        native_unit_of_measurement=f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}",
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data[DATA_GAS].tomorrow_average_price,
    ),
    FrankEnergieEntityDescription(
        key="actual_costs_until_last_meter_reading_date",
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
    FrankEnergieEntityDescription(
        key="costs_this_year",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        authenticated=True,
        service_name=SERVICE_NAME_COSTS,
        value_fn=lambda data: (
            round(data[DATA_INVOICES].total_costs_this_year, 2) if data[DATA_INVOICES] is not None else None
        ),
        attr_fn=lambda data, tz: _yearly_invoices_attrs(data, dt_util.utcnow().year),
    ),
    FrankEnergieEntityDescription(
        key="costs_previous_year",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        authenticated=True,
        service_name=SERVICE_NAME_COSTS,
        value_fn=lambda data: (
            round(data[DATA_INVOICES].total_costs_previous_year, 2) if data[DATA_INVOICES] is not None else None
        ),
        attr_fn=lambda data, tz: _yearly_invoices_attrs(data, dt_util.utcnow().year - 1),
    ),
)


@dataclass
class UsageEntityDescription(SensorEntityDescription):
    """Describes a Frank Energie daily/monthly usage or costs sensor entity."""

    value_fn: Callable[[UsageData | None], StateType] = None
    attr_fn: Callable[[UsageData | None, tzinfo], dict[str, Any]] = lambda _data, _tz: {}
    last_reset_fn: Callable[[UsageData | None], Any] = lambda _data: None
    is_gas: bool = False
    is_feed_in: bool = False


def _daily_category(data: UsageData | None, name: str) -> EnergyCategory | None:
    """Return `data.daily.<name>` (electricity/gas/feed_in), or None when unavailable."""
    if data is None or data.daily is None:
        return None
    return getattr(data.daily, name)


def _daily_usage(data: UsageData | None, name: str) -> StateType:
    category = _daily_category(data, name)
    return category.usage_total if category is not None else None


def _daily_costs(data: UsageData | None, name: str) -> StateType:
    category = _daily_category(data, name)
    return category.costs_total if category is not None else None


def _localize_datetime(value: str, tz: tzinfo) -> Any:
    """Parse an ISO datetime string and localize it to `tz`, like other Frank Energie attributes."""
    parsed = dt_util.parse_datetime(value)
    return parsed.astimezone(tz) if parsed is not None else value


def _hours_attr(category: EnergyCategory | None, tz: tzinfo) -> list[dict[str, Any]] | None:
    """Build the "hours" attribute: a list of {from, till, usage, costs} per UsageItem."""
    if category is None:
        return None
    return [
        {
            "from": _localize_datetime(item.from_time, tz),
            "till": _localize_datetime(item.till_time, tz),
            "usage": item.usage,
            "costs": item.costs,
        }
        for item in category.items
    ]


def _daily_attrs(data: UsageData | None, name: str, tz: tzinfo) -> dict[str, Any]:
    """Build the shared "date"/"hours" attributes for a daily_usage sensor."""
    if data is None or data.daily_date is None:
        return {}
    attrs: dict[str, Any] = {"date": data.daily_date.isoformat()}
    hours = _hours_attr(_daily_category(data, name), tz)
    if hours is not None:
        attrs["hours"] = hours
    return attrs


def _daily_last_reset(data: UsageData | None) -> Any:
    """Return Amsterdam midnight of the covered day, for a daily_usage sensor's last_reset."""
    if data is None or data.daily_date is None:
        return None
    return datetime.combine(data.daily_date, time.min, tzinfo=dt_util.get_time_zone("Europe/Amsterdam"))


DAILY_USAGE_SENSOR_TYPES: tuple[UsageEntityDescription, ...] = (
    UsageEntityDescription(
        key="elec_usage_yesterday",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: _daily_usage(data, "electricity"),
        attr_fn=lambda data, tz: _daily_attrs(data, "electricity", tz),
        last_reset_fn=_daily_last_reset,
    ),
    UsageEntityDescription(
        key="elec_costs_yesterday",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda data: _daily_costs(data, "electricity"),
        attr_fn=lambda data, tz: _daily_attrs(data, "electricity", tz),
        last_reset_fn=_daily_last_reset,
    ),
    UsageEntityDescription(
        key="gas_usage_yesterday",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=2,
        value_fn=lambda data: _daily_usage(data, "gas"),
        attr_fn=lambda data, tz: _daily_attrs(data, "gas", tz),
        last_reset_fn=_daily_last_reset,
        is_gas=True,
    ),
    UsageEntityDescription(
        key="gas_costs_yesterday",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda data: _daily_costs(data, "gas"),
        attr_fn=lambda data, tz: _daily_attrs(data, "gas", tz),
        last_reset_fn=_daily_last_reset,
        is_gas=True,
    ),
    UsageEntityDescription(
        key="feed_in_yesterday",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: _daily_usage(data, "feed_in"),
        attr_fn=lambda data, tz: _daily_attrs(data, "feed_in", tz),
        last_reset_fn=_daily_last_reset,
        is_feed_in=True,
    ),
    UsageEntityDescription(
        key="feed_in_revenue_yesterday",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda data: _daily_costs(data, "feed_in"),
        attr_fn=lambda data, tz: _daily_attrs(data, "feed_in", tz),
        last_reset_fn=_daily_last_reset,
        is_feed_in=True,
    ),
)


def _monthly_difference(data: UsageData | None, name: str) -> Any:
    """Return `data.monthly.<name>Difference`, or None when unavailable."""
    if data is None or data.monthly is None:
        return None
    return getattr(data.monthly, name)


# month_insights reports feed-in usage and revenue as negative numbers, while
# period_usage_and_costs (the daily sensors) reports them as positive. Flip the
# monthly ones so feed-in is always positive kWh and revenue positive euros.
_NEGATED_FEED_IN_FIELDS = {"actualUsage", "actualCosts", "expectedUsage", "expectedCosts"}


def _monthly_value(data: UsageData | None, name: str, field: str) -> StateType:
    difference = _monthly_difference(data, name)
    if difference is None:
        return None
    value = getattr(difference, field)
    if name == "feedInDifference" and field in _NEGATED_FEED_IN_FIELDS and value is not None:
        return -value
    return value


def _monthly_attrs(data: UsageData | None, extra: dict[str, Any]) -> dict[str, Any]:
    """Build the shared "last_meter_reading" attribute for a monthly_usage sensor, plus `extra`."""
    if data is None or data.monthly is None:
        return {}
    return {"last_meter_reading": data.monthly.lastMeterReadingDate, **extra}


def _monthly_usage_attrs(data: UsageData | None, name: str) -> dict[str, Any]:
    return _monthly_attrs(data, {"expected_usage": _monthly_value(data, name, "expectedUsage")})


def _monthly_costs_attrs(data: UsageData | None, name: str) -> dict[str, Any]:
    return _monthly_attrs(
        data,
        {
            "expected_costs": _monthly_value(data, name, "expectedCosts"),
            "average_price": _monthly_value(data, name, "actualAverageUnitPrice"),
        },
    )


def _monthly_last_reset(data: UsageData | None) -> Any:
    """Return the start of the current month in Europe/Amsterdam, for a monthly_usage sensor's last_reset.

    Statistics for these TOTAL sensors would otherwise go negative on the 1st
    of the month, when this month's actual usage/costs reset to a value lower
    than last month's.
    """
    if data is None or data.monthly is None:
        return None
    tz = dt_util.get_time_zone("Europe/Amsterdam")
    return datetime.combine(dt_util.now(tz).date().replace(day=1), time.min, tzinfo=tz)


MONTHLY_USAGE_SENSOR_TYPES: tuple[UsageEntityDescription, ...] = (
    UsageEntityDescription(
        key="elec_usage_month",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: _monthly_value(data, "electricityDifference", "actualUsage"),
        attr_fn=lambda data, tz: _monthly_usage_attrs(data, "electricityDifference"),
        last_reset_fn=_monthly_last_reset,
    ),
    UsageEntityDescription(
        key="elec_costs_month",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda data: _monthly_value(data, "electricityDifference", "actualCosts"),
        attr_fn=lambda data, tz: _monthly_costs_attrs(data, "electricityDifference"),
        last_reset_fn=_monthly_last_reset,
    ),
    UsageEntityDescription(
        key="gas_usage_month",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=2,
        value_fn=lambda data: _monthly_value(data, "gasDifference", "actualUsage"),
        attr_fn=lambda data, tz: _monthly_usage_attrs(data, "gasDifference"),
        last_reset_fn=_monthly_last_reset,
        is_gas=True,
    ),
    UsageEntityDescription(
        key="gas_costs_month",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda data: _monthly_value(data, "gasDifference", "actualCosts"),
        attr_fn=lambda data, tz: _monthly_costs_attrs(data, "gasDifference"),
        last_reset_fn=_monthly_last_reset,
        is_gas=True,
    ),
    UsageEntityDescription(
        key="feed_in_month",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: _monthly_value(data, "feedInDifference", "actualUsage"),
        attr_fn=lambda data, tz: _monthly_usage_attrs(data, "feedInDifference"),
        last_reset_fn=_monthly_last_reset,
        is_feed_in=True,
    ),
    UsageEntityDescription(
        key="feed_in_revenue_month",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda data: _monthly_value(data, "feedInDifference", "actualCosts"),
        attr_fn=lambda data, tz: _monthly_costs_attrs(data, "feedInDifference"),
        last_reset_fn=_monthly_last_reset,
        is_feed_in=True,
    ),
    UsageEntityDescription(
        key="fixed_costs_month",
        device_class=SensorDeviceClass.MONETARY,
        state_class=None,
        native_unit_of_measurement=CURRENCY_EURO,
        suggested_display_precision=2,
        value_fn=lambda data: data.monthly.expectedCostsFixed if data is not None and data.monthly else None,
        attr_fn=lambda data, tz: _monthly_attrs(data, {}),
    ),
)


def _usage_has_gas(data: UsageData | None) -> bool:
    """Return whether gas usage data is available, to decide whether to create gas usage sensors.

    Defaults to True (create the sensors) unless the fetched data clearly
    shows there is no gas, so a daily response where gas simply hasn't been
    published yet (electricity is also None in that case) doesn't
    permanently hide them.
    """
    if data is None:
        return True
    if data.daily is not None and data.daily.electricity is not None and data.daily.gas is None:
        return False
    if data.monthly is not None and data.monthly.gasExcluded:
        return False
    return True


def _difference_has_no_usage(difference: Difference) -> bool:
    """Return whether a monthly Difference clearly shows no usage at all (actual and expected both zero)."""
    return difference.actualUsage == 0 and difference.expectedUsage == 0


def _usage_has_feed_in(data: UsageData | None) -> bool:
    """Return whether feed-in usage data is available, to decide whether to create feed-in usage sensors.

    Defaults to True (create the sensors) unless the fetched data clearly
    shows there is no feed-in (no solar), using the same "clearly has data"
    rule as _usage_has_gas().
    """
    if data is None:
        return True
    if data.daily is not None and data.daily.electricity is not None and data.daily.feed_in is None:
        return False
    if data.monthly is not None and _difference_has_no_usage(data.monthly.feedInDifference):
        return False
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frank Energie sensor entries."""
    runtime_data = config_entry.runtime_data
    frank_coordinator = runtime_data.coordinator
    price_analysis_coordinator = runtime_data.price_analysis
    usage_coordinator = runtime_data.usage
    contract_coordinator = runtime_data.contract
    groups = enabled_groups(config_entry)

    # Add an entity for each sensor type, when authenticated is True, only
    # add the entity if the user is authenticated. Current-price sensors
    # (absent from SENSOR_GROUP_BY_KEY) are always created; the others only
    # when their sensor group is enabled.
    entities: list[SensorEntity] = [
        FrankEnergieSensor(frank_coordinator, description, config_entry)
        for description in SENSOR_TYPES
        if (not description.authenticated or frank_coordinator.api.is_authenticated)
        and key_enabled(description.key, groups)
    ]
    async_add_entities(entities, True)

    # price_analysis_coordinator is None when the price_analysis sensor group
    # is disabled (see __init__.py): no PriceAnalysisCoordinator is created
    # or refreshed in that case, so these entities are skipped entirely.
    #
    # The price analysis entities read PriceAnalysisCoordinator.data, which is
    # already populated (async_setup_entry awaits the coordinator's first
    # refresh before setting up any platform): update_before_add=False avoids
    # an extra (and, for CoordinatorEntity.async_update(), coordinator-wide)
    # recomputation, including a redundant solar forecast fetch, per entity.
    if price_analysis_coordinator is not None:
        async_add_entities(
            [
                FrankEnergiePriceLevelSensor(price_analysis_coordinator, config_entry),
                FrankEnergiePriceAnalysisDaySensor(price_analysis_coordinator, config_entry, "today"),
                FrankEnergiePriceAnalysisDaySensor(price_analysis_coordinator, config_entry, "tomorrow"),
                FrankEnergieNextCheapestPeriodSensor(price_analysis_coordinator, config_entry),
            ],
            False,
        )

    # usage_coordinator is None when neither daily_usage nor monthly_usage is
    # enabled, or the entry isn't authenticated (see __init__.py). Gas/feed-in
    # sensors are only created when the first refresh's data has gas/feed-in;
    # see _usage_has_gas()/_usage_has_feed_in().
    if usage_coordinator is not None:
        has_gas = _usage_has_gas(usage_coordinator.data)
        has_feed_in = _usage_has_feed_in(usage_coordinator.data)
        usage_entities = [
            FrankEnergieUsageSensor(usage_coordinator, description, config_entry)
            for description in (*DAILY_USAGE_SENSOR_TYPES, *MONTHLY_USAGE_SENSOR_TYPES)
            if key_enabled(description.key, groups)
            and (not description.is_gas or has_gas)
            and (not description.is_feed_in or has_feed_in)
        ]
        async_add_entities(usage_entities, False)

    # contract_coordinator is None when the entry isn't authenticated or the
    # costs sensor group is disabled (see __init__.py).
    if contract_coordinator is not None:
        async_add_entities([PriceResolutionSensor(contract_coordinator, config_entry)], False)


class FrankEnergieSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Frank Energie sensor."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = ICON
    _attr_has_entity_name = True
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
        self._attr_translation_key = description.key
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
    _attr_has_entity_name = True
    coordinator: PriceAnalysisCoordinator

    def __init__(self, coordinator: PriceAnalysisCoordinator, key: str, entry: ConfigEntry) -> None:
        """Initialize the price analysis entity."""
        self._attr_unique_id = f"{entry.unique_id}.{key}"
        self._attr_translation_key = key
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

    def __init__(self, coordinator: PriceAnalysisCoordinator, entry: ConfigEntry) -> None:
        """Initialize the price level sensor."""
        super().__init__(coordinator, "price_level", entry)

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
        super().__init__(coordinator, key, entry)

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
        super().__init__(coordinator, "next_cheapest_period", entry)

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


class FrankEnergieUsageSensor(CoordinatorEntity, SensorEntity):
    """Representation of a daily/monthly usage or costs sensor, backed by UsageCoordinator."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    # The "hours" attribute holds up to 24 hourly usage/cost entries; keep it
    # out of the recorder like the "prices"/price-analysis attributes above.
    _unrecorded_attributes = frozenset({"hours"})
    coordinator: UsageCoordinator

    def __init__(
        self, coordinator: UsageCoordinator, description: UsageEntityDescription, entry: ConfigEntry
    ) -> None:
        """Initialize the usage sensor."""
        self.entity_description: UsageEntityDescription = description
        self._attr_unique_id = f"{entry.unique_id}.{description.key}"
        self._attr_translation_key = description.key
        self._attr_device_info = device_info(entry, SERVICE_NAME_COSTS)
        # Only force the currency icon for monetary sensors; the
        # ENERGY/GAS device-class usage sensors use HA's own device-class
        # icons instead.
        if description.device_class == SensorDeviceClass.MONETARY:
            self._attr_icon = ICON
        super().__init__(coordinator)

    @property
    def native_value(self) -> StateType:
        try:
            return self.entity_description.value_fn(self.coordinator.data)
        except _NO_DATA_ERRORS:
            return None

    @property
    def last_reset(self):
        try:
            return self.entity_description.last_reset_fn(self.coordinator.data)
        except _NO_DATA_ERRORS:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        try:
            tz = self.coordinator.price_coordinator.prices_tzinfo
            return self.entity_description.attr_fn(self.coordinator.data, tz)
        except _NO_DATA_ERRORS:
            return {}

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None


_PRICE_RESOLUTION_OPTIONS = ("PT15M", "PT60M")


def _iso_date(value: Any) -> str | None:
    """Return `value` as an ISO date string, whether it is already a str, a date, or None."""
    if value is None or isinstance(value, str):
        return value
    return value.isoformat()


class PriceResolutionSensor(CoordinatorEntity, SensorEntity):
    """The contract's price resolution (PT15M/PT60M), backed by ContractCoordinator."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_translation_key = "price_resolution"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(_PRICE_RESOLUTION_OPTIONS)
    coordinator: ContractCoordinator

    def __init__(self, coordinator: ContractCoordinator, entry: ConfigEntry) -> None:
        """Initialize the price resolution sensor."""
        self._attr_unique_id = f"{entry.unique_id}.price_resolution"
        self._attr_device_info = device_info(entry, SERVICE_NAME_COSTS)
        super().__init__(coordinator)

    @property
    def native_value(self) -> StateType:
        state = self.coordinator.data
        if state is None or state.active_option not in _PRICE_RESOLUTION_OPTIONS:
            return None
        return state.active_option

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.coordinator.data
        if state is None:
            return {}
        return {
            "available_options": state.available_options,
            "is_change_request_possible": state.is_change_request_possible,
            "upcoming_change": _iso_date(state.upcoming_change),
            "upcoming_change_effective_date": _iso_date(state.upcoming_change_effective_date),
            "change_request_effective_date": _iso_date(state.change_request_effective_date),
        }

    @property
    def available(self) -> bool:
        """Unavailable when no electricity connection was found (ContractCoordinator.data is None)."""
        return super().available and self.coordinator.data is not None
