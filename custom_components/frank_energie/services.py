"""Services for the Frank Energie integration."""
from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util
from python_frank_energie.models import Price, PriceData

from .const import CONF_COORDINATOR, DATA_ELECTRICITY, DATA_GAS, DOMAIN

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_START = "start"
ATTR_END = "end"

SERVICE_GET_PRICES = "get_prices"

SERVICE_GET_PRICES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_START): cv.datetime,
        vol.Optional(ATTR_END): cv.datetime,
    }
)


def _resolve_loaded_entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry:
    """Return the loaded Frank Energie config entry for `entry_id`, or raise ServiceValidationError."""
    entry = hass.config_entries.async_get_entry(entry_id)

    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )

    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"entry_id": entry_id},
        )

    return entry


def _filter_slots(price_data: PriceData, start, end) -> list[Price]:
    """Return the price slots of `price_data` that overlap [start, end)."""
    return [
        price
        for price in price_data.price_data
        if (start is None or price.date_till > start) and (end is None or price.date_from < end)
    ]


def _serialize_price(price: Price, tz: ZoneInfo) -> dict[str, Any]:
    """Serialize a single Price slot for the get_prices service response."""
    return {
        "start": price.date_from.astimezone(tz).isoformat(),
        "end": price.date_till.astimezone(tz).isoformat(),
        "price": round(price.total, 5),
        "market_price": round(price.market_price, 5),
        "market_price_including_tax": round(price.market_price_with_tax, 5),
        "vat": round(price.market_price_tax, 5),
        "sourcing_markup": round(price.sourcing_markup_price, 5),
        "energy_tax": round(price.energy_tax_price, 5),
    }


async def _async_get_prices(call: ServiceCall) -> ServiceResponse:
    """Handle the get_prices service call."""
    hass = call.hass
    entry = _resolve_loaded_entry(hass, call.data[ATTR_CONFIG_ENTRY_ID])

    start = dt_util.as_utc(call.data[ATTR_START]) if ATTR_START in call.data else None
    end = dt_util.as_utc(call.data[ATTR_END]) if ATTR_END in call.data else None

    if start is not None and end is not None and start >= end:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_period",
        )

    coordinator = hass.data[DOMAIN][entry.entry_id][CONF_COORDINATOR]
    data = coordinator.data
    tz = coordinator.prices_tzinfo

    electricity = _filter_slots(data[DATA_ELECTRICITY], start, end) if data else []
    gas = _filter_slots(data[DATA_GAS], start, end) if data else []

    return {
        "electricity": [_serialize_price(price, tz) for price in electricity],
        "gas": [_serialize_price(price, tz) for price in gas],
    }


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Frank Energie services."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PRICES,
        _async_get_prices,
        schema=SERVICE_GET_PRICES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
