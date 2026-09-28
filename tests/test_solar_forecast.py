"""Unit tests for the solar forecast helper's error paths (solar_forecast.py).

`async_get_solar_forecast_wh_hours` must never raise: any of a missing entry
selection, an unknown entry, an unloaded entry, the energy platform's
forecast call raising, or the entry's domain not providing a solar forecast
platform at all must all result in {} (no solar), never an exception.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.frank_energie.solar_forecast import async_get_solar_forecast_wh_hours


@pytest.mark.parametrize(
    "case",
    [
        "no_entry_selected",
        "unknown_entry",
        "unloaded_entry",
        "platform_raises",
        "domain_without_platform",
    ],
)
async def test_solar_forecast_error_paths_return_empty(hass, monkeypatch, case):
    """Every documented error path returns {} instead of raising."""
    entry_id: str | None = None
    platforms: dict = {}

    if case == "no_entry_selected":
        entry_id = None
    elif case == "unknown_entry":
        entry_id = "does-not-exist"
    elif case == "unloaded_entry":
        entry = MockConfigEntry(domain="fake_solar", unique_id="fake-solar-1")
        entry.add_to_hass(hass)
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
        entry_id = entry.entry_id
        # A platform that *would* return real data, so the test only passes
        # if the not-loaded entry is actually rejected before this is used.
        platforms = {"fake_solar": AsyncMock(return_value={"wh_hours": {"2024-01-01T00:00:00+00:00": 1000.0}})}
    elif case == "platform_raises":
        entry = MockConfigEntry(domain="fake_solar", unique_id="fake-solar-1")
        entry.add_to_hass(hass)
        entry.mock_state(hass, ConfigEntryState.LOADED)
        entry_id = entry.entry_id
        platforms = {"fake_solar": AsyncMock(side_effect=RuntimeError("boom"))}
    elif case == "domain_without_platform":
        entry = MockConfigEntry(domain="fake_solar", unique_id="fake-solar-1")
        entry.add_to_hass(hass)
        entry.mock_state(hass, ConfigEntryState.LOADED)
        entry_id = entry.entry_id
        platforms = {}

    async def fake_get_energy_platforms(_hass):
        return platforms

    monkeypatch.setattr(
        "homeassistant.components.energy.websocket_api.async_get_energy_platforms",
        fake_get_energy_platforms,
    )

    result = await async_get_solar_forecast_wh_hours(hass, entry_id)

    assert result == {}
