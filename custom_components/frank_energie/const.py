"""Constants for the Frank Energie integration."""
from __future__ import annotations

ATTRIBUTION = "Data provided by Frank Energie"
DOMAIN = "frank_energie"
DATA_URL = "https://frank-graphql-prod.graphcdn.app/"
ICON = "mdi:currency-eur"
COMPONENT_TITLE = "Frank Energie"

CONF_COORDINATOR = "coordinator"
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
