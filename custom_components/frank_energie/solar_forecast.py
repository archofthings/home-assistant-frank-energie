"""Helper to fetch the solar production forecast for the configured energy platform entry."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_get_solar_forecast_wh_hours(hass: HomeAssistant, entry_id: str | None) -> dict[str, float]:
    """Return the `wh_hours` solar forecast for `entry_id`, or {} when unavailable.

    Looks up `entry_id`'s domain and, via
    `homeassistant.components.energy.websocket_api.async_get_energy_platforms`
    (a hass-cached singleton mapping domain -> that domain's
    `async_get_solar_forecast`), awaits that platform's forecast for the
    entry. Never raises: a missing/unloaded entry, an import failure, a
    domain without a solar forecast platform, or any other error while
    fetching the forecast is logged at debug level and results in {}.
    """
    if not entry_id:
        return {}

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        _LOGGER.debug("Solar forecast entry %s is missing or not loaded", entry_id)
        return {}

    try:
        from homeassistant.components.energy.websocket_api import (  # pylint: disable=import-outside-toplevel
            async_get_energy_platforms,
        )

        platforms = await async_get_energy_platforms(hass)
        get_forecast = platforms.get(entry.domain)
        if get_forecast is None:
            _LOGGER.debug("Domain %s does not provide a solar forecast platform", entry.domain)
            return {}

        forecast = await get_forecast(hass, entry_id)
    except Exception as ex:  # noqa: BLE001 - best-effort fetch from a foreign integration
        _LOGGER.debug("Could not fetch solar forecast for entry %s: %s", entry_id, ex)
        return {}

    if not forecast:
        return {}

    return forecast.get("wh_hours", {})
