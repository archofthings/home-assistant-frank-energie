"""Constants for the Frank Energie integration."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

ATTRIBUTION = "Data provided by Frank Energie"
DOMAIN = "frank_energie"
DATA_URL = "https://frank-graphql-prod.graphcdn.app/"
ICON = "mdi:currency-eur"
COMPONENT_TITLE = "Frank Energie"

CONF_COORDINATOR = "coordinator"
CONF_USAGE_COORDINATOR = "usage_coordinator"
ATTR_TIME = "from_time"

CONF_PRICES_TIMEZONE = "prices_timezone"
PRICES_TIMEZONE_HOME_ASSISTANT = "home_assistant"
PRICES_TIMEZONE_UTC = "utc"

DATA_ELECTRICITY = "electricity"
DATA_GAS = "gas"
DATA_MONTH_SUMMARY = "month_summary"
DATA_INVOICES = "invoices"

SERVICE_NAME_PRICES = "Prices"
SERVICE_NAME_COSTS = "Costs"

# Price analysis options (see analysis.py and price_analysis.py).
CONF_PRICE_ANALYSIS = "price_analysis"
CONF_CHEAP_PRICE_THRESHOLD = "cheap_price_threshold"
CONF_EXPENSIVE_PRICE_THRESHOLD = "expensive_price_threshold"
CONF_CHEAPEST_PERIOD_MINUTES = "cheapest_period_minutes"
CONF_SOLAR_FORECAST_ENTRY = "solar_forecast_entry"
CONF_SOLAR_THRESHOLD_KWH = "solar_threshold_kwh"

DEFAULT_CHEAP_PRICE_THRESHOLD = 0.25
DEFAULT_EXPENSIVE_PRICE_THRESHOLD = 0.40
DEFAULT_CHEAPEST_PERIOD_MINUTES = 120
DEFAULT_SOLAR_THRESHOLD_KWH = 1.5

PRICE_LEVEL_CHEAP_SOLAR = "cheap_solar"
PRICE_LEVEL_CHEAP = "cheap"
PRICE_LEVEL_NORMAL = "normal"
PRICE_LEVEL_EXPENSIVE = "expensive"
PRICE_LEVELS = (PRICE_LEVEL_CHEAP_SOLAR, PRICE_LEVEL_CHEAP, PRICE_LEVEL_NORMAL, PRICE_LEVEL_EXPENSIVE)

# Selectable sensor groups (see CONF_SENSOR_GROUPS below). "Current prices"
# (elec_markup/market/tax/tax_vat/sourcing/tax_only and their gas
# equivalents) are always created and are not part of any group.
CONF_SENSOR_GROUPS = "sensor_groups"
SENSOR_GROUP_DAILY_STATISTICS = "daily_statistics"
SENSOR_GROUP_UPCOMING = "upcoming"
SENSOR_GROUP_PRICE_ANALYSIS = "price_analysis"
SENSOR_GROUP_COSTS = "costs"
SENSOR_GROUP_DAILY_USAGE = "daily_usage"
SENSOR_GROUP_MONTHLY_USAGE = "monthly_usage"
SENSOR_GROUPS = (
    SENSOR_GROUP_DAILY_STATISTICS,
    SENSOR_GROUP_UPCOMING,
    SENSOR_GROUP_PRICE_ANALYSIS,
    SENSOR_GROUP_COSTS,
    SENSOR_GROUP_DAILY_USAGE,
    SENSOR_GROUP_MONTHLY_USAGE,
)
DEFAULT_SENSOR_GROUPS = [SENSOR_GROUP_DAILY_STATISTICS, SENSOR_GROUP_COSTS]

# The groups that existed before daily_usage/monthly_usage were added: the
# fallback enabled_groups() uses for a legacy entry with no CONF_SENSOR_GROUPS
# option stored, so such an entry keeps exactly its previous behaviour
# instead of gaining the two new, off-by-default groups.
LEGACY_SENSOR_GROUPS = (
    SENSOR_GROUP_DAILY_STATISTICS,
    SENSOR_GROUP_UPCOMING,
    SENSOR_GROUP_PRICE_ANALYSIS,
    SENSOR_GROUP_COSTS,
)

# Sensor groups only offered as a choice (and only ever selectable) for a
# logged-in entry; see config_flow._init_schema/OptionsFlowHandler.async_step_init.
SENSOR_GROUPS_REQUIRE_LOGIN = (SENSOR_GROUP_COSTS, SENSOR_GROUP_DAILY_USAGE, SENSOR_GROUP_MONTHLY_USAGE)

# Maps each grouped sensor/binary_sensor entity description key to its
# sensor group. Keys absent from this dict (the "current prices" sensors)
# are always created. The price_analysis_today/tomorrow sensors are built
# dynamically (key = f"price_analysis_{period}"), not from SENSOR_TYPES.
SENSOR_GROUP_BY_KEY: dict[str, str] = {
    "elec_min": SENSOR_GROUP_DAILY_STATISTICS,
    "elec_max": SENSOR_GROUP_DAILY_STATISTICS,
    "elec_avg": SENSOR_GROUP_DAILY_STATISTICS,
    "gas_min": SENSOR_GROUP_DAILY_STATISTICS,
    "gas_max": SENSOR_GROUP_DAILY_STATISTICS,
    "elec_next": SENSOR_GROUP_UPCOMING,
    "elec_tomorrow_avg": SENSOR_GROUP_UPCOMING,
    "elec_tomorrow_min": SENSOR_GROUP_UPCOMING,
    "elec_tomorrow_max": SENSOR_GROUP_UPCOMING,
    "elec_upcoming_min": SENSOR_GROUP_UPCOMING,
    "elec_upcoming_max": SENSOR_GROUP_UPCOMING,
    "gas_tomorrow_avg": SENSOR_GROUP_UPCOMING,
    "price_level": SENSOR_GROUP_PRICE_ANALYSIS,
    "price_analysis_today": SENSOR_GROUP_PRICE_ANALYSIS,
    "price_analysis_tomorrow": SENSOR_GROUP_PRICE_ANALYSIS,
    "next_cheapest_period": SENSOR_GROUP_PRICE_ANALYSIS,
    "cheap_price_now": SENSOR_GROUP_PRICE_ANALYSIS,
    "cheapest_period_now": SENSOR_GROUP_PRICE_ANALYSIS,
    "actual_costs_until_last_meter_reading_date": SENSOR_GROUP_COSTS,
    "expected_costs_until_last_meter_reading_date": SENSOR_GROUP_COSTS,
    "expected_costs_this_month": SENSOR_GROUP_COSTS,
    "invoice_previous_period": SENSOR_GROUP_COSTS,
    "invoice_current_period": SENSOR_GROUP_COSTS,
    "invoice_upcoming_period": SENSOR_GROUP_COSTS,
}


def key_enabled(key: str, groups: set[str]) -> bool:
    """Return whether `key`'s sensor group (if any) is among the enabled `groups`.

    Keys absent from SENSOR_GROUP_BY_KEY (the "current prices" sensors) are
    always enabled.
    """
    group = SENSOR_GROUP_BY_KEY.get(key)
    return group is None or group in groups


def enabled_groups(entry: "ConfigEntry") -> set[str]:
    """Return the sensor groups enabled for `entry`.

    Entries without CONF_SENSOR_GROUPS in their options (i.e. created before
    this feature existed) default to all groups enabled, computed here
    rather than migrated, so nothing disappears after an update.
    """
    groups = entry.options.get(CONF_SENSOR_GROUPS)
    return set(groups) if groups is not None else set(SENSOR_GROUPS)
