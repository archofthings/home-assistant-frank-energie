"""Diagnostics support for Frank Energie."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant
from python_frank_energie.models import PriceData

from .const import (
    DATA_ELECTRICITY,
    DATA_GAS,
    DATA_INVOICES,
    DATA_MONTH_SUMMARY,
    enabled_groups,
)
from .contract import ContractCoordinator
from .coordinator import FrankEnergieCoordinator
from .usage import UsageCoordinator

CONTRACT_TO_REDACT = {"connection_id"}

TO_REDACT = {CONF_ACCESS_TOKEN, CONF_TOKEN, CONF_USERNAME, "site_reference", "title", "unique_id"}


def _redact_message(message: str, entry: ConfigEntry | None) -> str:
    """Replace any occurrence of `entry`'s tokens, username or site_reference in `message`.

    Exception messages (e.g. from a failed request) can otherwise echo those
    values back verbatim.
    """
    if entry is None:
        return message

    sensitive_values = (
        entry.data.get(CONF_ACCESS_TOKEN),
        entry.data.get(CONF_TOKEN),
        entry.data.get(CONF_USERNAME),
        entry.data.get("site_reference"),
    )
    for value in sensitive_values:
        if value:
            message = message.replace(str(value), "**REDACTED**")
    return message


def _serialize_exception(ex: BaseException | None, entry: ConfigEntry | None = None) -> str | None:
    """Return the exception's class name and message only, never a full traceback.

    Any occurrence of `entry`'s tokens, username or site_reference in the
    message is redacted; see `_redact_message`.
    """
    if ex is None:
        return None
    return _redact_message(f"{type(ex).__name__}: {ex}", entry)


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
        "sensor_groups": sorted(enabled_groups(entry)),
    }


def _diagnostics_coordinator(coordinator: FrankEnergieCoordinator) -> dict[str, Any]:
    """Build the "coordinator" section of the diagnostics."""
    update_interval = coordinator.update_interval
    return {
        "last_update_success": coordinator.last_update_success,
        "last_exception": _serialize_exception(coordinator.last_exception, coordinator.entry),
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


def _diagnostics_usage(usage_coordinator: UsageCoordinator | None) -> dict[str, Any]:
    """Build the "usage" section of the diagnostics: whether it exists, its status and the date covered."""
    if usage_coordinator is None:
        return {"exists": False, "last_update_success": None, "daily_date": None, "monthly_available": False}

    data = usage_coordinator.data
    return {
        "exists": True,
        "last_update_success": usage_coordinator.last_update_success,
        "daily_date": data.daily_date.isoformat() if data is not None and data.daily_date is not None else None,
        "monthly_available": data is not None and data.monthly is not None,
    }


def _diagnostics_contract(contract_coordinator: ContractCoordinator | None) -> dict[str, Any]:
    """Build the "contract" section of the diagnostics: the price resolution state, connection id redacted."""
    if contract_coordinator is None:
        return {"exists": False}

    state = contract_coordinator.data
    return async_redact_data(
        {
            "exists": True,
            "last_update_success": contract_coordinator.last_update_success,
            "connection_id": contract_coordinator.connection_id,
            "active_option": state.active_option if state is not None else None,
            "available_options": state.available_options if state is not None else None,
            "is_change_request_possible": state.is_change_request_possible if state is not None else None,
        },
        CONTRACT_TO_REDACT,
    )


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    `entry.runtime_data` is only set after a successful first refresh (see
    async_setup_entry), so entries stuck in SETUP_RETRY/SETUP_ERROR have no
    coordinator yet. Report the redacted "entry" section with
    "coordinator"/"data" set to None in that case, instead of raising
    AttributeError.
    """
    runtime_data = getattr(entry, "runtime_data", None)

    if runtime_data is None:
        return {
            "entry": _diagnostics_entry(entry),
            "coordinator": None,
            "data": None,
        }

    coordinator: FrankEnergieCoordinator = runtime_data.coordinator

    return {
        "entry": _diagnostics_entry(entry),
        "coordinator": _diagnostics_coordinator(coordinator),
        "data": _diagnostics_data(coordinator),
        "usage": _diagnostics_usage(runtime_data.usage),
        "contract": _diagnostics_contract(runtime_data.contract),
    }
