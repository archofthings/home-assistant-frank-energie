"""Diagnostics support for Frank Energie."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant
from python_frank_energie.models import PriceData

from .const import CONF_COORDINATOR, DATA_ELECTRICITY, DATA_GAS, DATA_INVOICES, DATA_MONTH_SUMMARY, DOMAIN
from .coordinator import FrankEnergieCoordinator

TO_REDACT = {CONF_ACCESS_TOKEN, CONF_TOKEN, CONF_USERNAME, "site_reference", "title", "unique_id"}


def _serialize_exception(ex: BaseException | None) -> str | None:
    """Return the exception's class name and message only, never a full traceback."""
    if ex is None:
        return None
    return f"{type(ex).__name__}: {ex}"


def _serialize_price_data(price_data: PriceData | None) -> dict[str, Any]:
    """Summarize a PriceData object without leaking the individual price slots."""
    if price_data is None or not price_data.price_data:
        return {
            "slot_count": 0,
            "resolution_minutes": price_data.resolution_minutes if price_data is not None else None,
            "first_date_from": None,
            "last_date_till": None,
            "has_tomorrow": False,
        }

    slots = price_data.price_data
    return {
        "slot_count": len(slots),
        "resolution_minutes": price_data.resolution_minutes,
        "first_date_from": slots[0].date_from.isoformat(),
        "last_date_till": slots[-1].date_till.isoformat(),
        "has_tomorrow": bool(price_data.tomorrow_prices),
    }


def _diagnostics_entry(entry: ConfigEntry) -> dict[str, Any]:
    """Build the redacted "entry" section of the diagnostics."""
    redacted = async_redact_data(
        {"data": dict(entry.data), "title": entry.title, "unique_id": entry.unique_id},
        TO_REDACT,
    )
    return {
        **redacted,
        "version": entry.version,
        "state": entry.state.value,
    }


def _diagnostics_coordinator(coordinator: FrankEnergieCoordinator) -> dict[str, Any]:
    """Build the "coordinator" section of the diagnostics."""
    update_interval = coordinator.update_interval
    return {
        "last_update_success": coordinator.last_update_success,
        "last_exception": _serialize_exception(coordinator.last_exception),
        "update_interval": update_interval.total_seconds() if update_interval is not None else None,
        "user_country": coordinator.user_country,
        "prices_timezone": coordinator.prices_timezone,
    }


def _diagnostics_data(coordinator: FrankEnergieCoordinator) -> dict[str, Any]:
    """Build the "data" section of the diagnostics."""
    data = coordinator.data

    electricity = data[DATA_ELECTRICITY] if data is not None else None
    gas = data[DATA_GAS] if data is not None else None
    month_summary = data[DATA_MONTH_SUMMARY] if data is not None else None
    invoices = data[DATA_INVOICES] if data is not None else None

    return {
        "electricity": _serialize_price_data(electricity),
        "gas": _serialize_price_data(gas),
        "month_summary_available": month_summary is not None,
        "invoices_available": invoices is not None,
    }


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: FrankEnergieCoordinator = hass.data[DOMAIN][entry.entry_id][CONF_COORDINATOR]

    return {
        "entry": _diagnostics_entry(entry),
        "coordinator": _diagnostics_coordinator(coordinator),
        "data": _diagnostics_data(coordinator),
    }
