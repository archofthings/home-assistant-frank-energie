"""Helper to fetch the solar production forecast for the configured energy platform entry."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Logged as a WARNING only once per Home Assistant run (see
# warn_energy_platforms_import_failed_once below), shared with config_flow.py's
# own energy platforms lookup; every other error while fetching a solar
# forecast is expected to be foreign-integration noise and stays at debug level.
_warned_energy_platforms_import_failed = False


def warn_energy_platforms_import_failed_once(ex: Exception) -> None:
    """Log a one-time WARNING that the energy platforms lookup couldn't be imported."""
    global _warned_energy_platforms_import_failed
    if _warned_energy_platforms_import_failed:
        return
    _warned_energy_platforms_import_failed = True
    _LOGGER.warning("Could not import the energy platforms lookup, solar forecasts are unavailable: %s", ex)


async def async_get_solar_forecast_wh_hours(hass: HomeAssistant, entry_id: str | None) -> dict[str, float]:
    """Return the `wh_hours` solar forecast for `entry_id`, or {} when unavailable.

    Looks up `entry_id`'s domain and, via
    `homeassistant.components.energy.websocket_api.async_get_energy_platforms`
    (a hass-cached singleton mapping domain -> that domain's
    `async_get_solar_forecast`), awaits that platform's forecast for the
    entry (both awaits guarded by a 10 second timeout, since either call is a
    foreign integration that could hang). Never raises: a missing/unloaded
    entry, an import failure, a domain without a solar forecast platform, a
    timeout, or any other error while fetching the forecast results in {}.
    An import failure is logged as a WARNING once per Home Assistant run (see
    `warn_energy_platforms_import_failed_once`); every other error is logged
    at debug level.
    """
    if not entry_id:
        return {}

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        _LOGGER.debug("Solar forecast entry %s is missing or not loaded", entry_id)
        return {}

    try:
        async with asyncio.timeout(10):
            try:
                from homeassistant.components.energy.websocket_api import (  # pylint: disable=import-outside-toplevel
                    async_get_energy_platforms,
                )
            except ImportError as ex:
                warn_energy_platforms_import_failed_once(ex)
                return {}

            platforms = await async_get_energy_platforms(hass)
            get_forecast = platforms.get(entry.domain)
            if get_forecast is None:
                _LOGGER.debug("Domain %s does not provide a solar forecast platform", entry.domain)
                return {}

            forecast = await get_forecast(hass, entry_id)
    except TimeoutError:
        _LOGGER.debug("Timed out fetching solar forecast for entry %s", entry_id)
        return {}
    except Exception as ex:  # noqa: BLE001 - best-effort fetch from a foreign integration
        _LOGGER.debug("Could not fetch solar forecast for entry %s: %s", entry_id, ex)
        return {}

    if not forecast:
        return {}

    return forecast.get("wh_hours", {})
