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
