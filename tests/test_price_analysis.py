"""Integration tests for the price analysis sensors and binary sensors."""
from __future__ import annotations

from datetime import timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.frank_energie import const
from custom_components.frank_energie.config_flow import SECTION_CHEAPEST_PERIOD, SECTION_PRICE_LEVELS
from tests.utils import install_prices, local_midnight

# Local midnight slot indices (15-minute slots): 10:00-10:15 local is slot 40.
CHEAP_SLOT_1 = 40
CHEAP_SLOT_2 = 41
EXPENSIVE_SLOT = 60


def entity_id_for_key(hass, entry, domain: str, key: str) -> str | None:
    """Look up an entity_id by its unique_id (f'{entry.unique_id}.{key}'), independent of slugging."""
    return er.async_get(hass).async_get_entity_id(domain, const.DOMAIN, f"{entry.unique_id}.{key}")


def state_for_key(hass, entry, domain: str, key: str) -> State | None:
    """Return the current state object for an entity by its description key."""
    entity_id = entity_id_for_key(hass, entry, domain, key)
    return hass.states.get(entity_id) if entity_id else None


def timestamp_state(value):
    """Return the expected `state` string for a TIMESTAMP sensor's `value`.

    Home Assistant always normalizes TIMESTAMP device class states to UTC
    (see homeassistant.components.sensor.SensorEntity.state), regardless of
    the tzinfo the entity's native_value carries; only extra_state_attributes
    follow coordinator.prices_tzinfo.
    """
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


async def setup_price_analysis_entry(
    hass,
    enable_custom_integrations,
    mock_frank_energie_class,
    freezer,
    monkeypatch,
    *,
    with_tomorrow: bool = False,
    prices_timezone: str = const.PRICES_TIMEZONE_HOME_ASSISTANT,
) -> MockConfigEntry:
    """Set up a Frank Energie entry with a known price pattern, thresholds and a fake solar forecast.

    Today (15-minute slots, local time): a flat 0.20 all-in price, except a
    30-minute cheap window at local 10:00-10:30 (0.10, the frozen "now") and
    an expensive slot at local 15:00-15:15 (0.50). Thresholds are cheap=0.15,
    expensive=0.35, cheapest_period_minutes=30 (so the 10:00-10:30 window is
    both the cheapest period and the only "cheap" window), solar_threshold_kwh=1.0.
    The fake solar platform's forecast covers the same 10:00-10:30 UTC hour
    with 1.5 kWh/h, so both of those slots also classify as "cheap_solar".
    """
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    electricity_today = [0.20] * 96
    electricity_today[CHEAP_SLOT_1] = 0.10
    electricity_today[CHEAP_SLOT_2] = 0.10
    electricity_today[EXPENSIVE_SLOT] = 0.50

    electricity_tomorrow = None
    if with_tomorrow:
        electricity_tomorrow = [0.20] * 96
        electricity_tomorrow[10] = 0.05
        electricity_tomorrow[11] = 0.05  # unambiguous 30-minute minimum (no tie with slot 9-10 or 10-11)

    install_prices(
        mock_frank_energie_class,
        electricity_today,
        [1.0] * 96,
        tomorrow_electricity=electricity_tomorrow,
        tomorrow_gas=[1.0] * 96 if with_tomorrow else None,
        resolution_minutes=15,
    )

    # The fake solar forecast's period start, aligned to the cheap slots' UTC hour.
    cheap_slot_start_utc = local_midnight().astimezone(timezone.utc) + timedelta(minutes=15 * CHEAP_SLOT_1)
    wh_hours = {
        cheap_slot_start_utc.isoformat(): 1500.0,
        (cheap_slot_start_utc + timedelta(minutes=60)).isoformat(): 0.0,
    }

    solar_entry = MockConfigEntry(domain="fake_solar", title="Fake solar", unique_id="fake-solar-1")
    solar_entry.add_to_hass(hass)
    solar_entry.mock_state(hass, ConfigEntryState.LOADED)

    async def fake_get_energy_platforms(_hass):
        return {"fake_solar": AsyncMock(return_value={"wh_hours": wh_hours})}

    monkeypatch.setattr(
        "homeassistant.components.energy.websocket_api.async_get_energy_platforms",
        fake_get_energy_platforms,
    )

    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        options={
            const.CONF_PRICES_TIMEZONE: prices_timezone,
            const.CONF_CHEAP_PRICE_THRESHOLD: 0.15,
            const.CONF_EXPENSIVE_PRICE_THRESHOLD: 0.35,
            const.CONF_CHEAPEST_PERIOD_MINUTES: 30,
            const.CONF_SOLAR_THRESHOLD_KWH: 1.0,
            const.CONF_SOLAR_FORECAST_ENTRY: solar_entry.entry_id,
        },
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return entry


async def test_price_level_sensor(
    hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
):
    """price_level reports the current slot's level (cheap_solar) and the configured thresholds."""
    entry = await setup_price_analysis_entry(
        hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
    )

    state = state_for_key(hass, entry, "sensor", "price_level")

    assert state.state == "cheap_solar"
    assert state.attributes["cheap_threshold"] == 0.15
    assert state.attributes["expensive_threshold"] == 0.35


async def test_cheap_price_now_binary_sensor(
    hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
):
    """cheap_price_now is on while the current level is cheap or cheap_solar."""
    entry = await setup_price_analysis_entry(
        hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
    )

    state = state_for_key(hass, entry, "binary_sensor", "cheap_price_now")

    assert state.state == "on"


async def test_cheapest_period_now_binary_sensor(
    hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
):
    """cheapest_period_now is on while now is within today's cheapest period."""
    entry = await setup_price_analysis_entry(
        hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
    )

    state = state_for_key(hass, entry, "binary_sensor", "cheapest_period_now")

    assert state.state == "on"

    # Advance past the cheapest 10:00-10:30 window and fire the coordinator's quarter-hour timer.
    freezer.move_to("2026-01-15 11:00:00+01:00")
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()

    assert state_for_key(hass, entry, "binary_sensor", "cheapest_period_now").state == "off"


async def test_price_analysis_today_sensor(
    hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
):
    """price_analysis_today reports the cheapest period's start and the expected slots/windows/thresholds."""
    entry = await setup_price_analysis_entry(
        hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
    )

    state = state_for_key(hass, entry, "sensor", "price_analysis_today")

    expected_start = local_midnight() + timedelta(minutes=15 * CHEAP_SLOT_1)
    assert state.state == timestamp_state(expected_start)

    cheapest_period = state.attributes["cheapest_period"]
    assert cheapest_period["average_price"] == 0.1
    assert cheapest_period["minutes"] == 30

    assert len(state.attributes["cheap_windows"]) == 1
    assert len(state.attributes["solar_windows"]) == 1
    assert len(state.attributes["expensive_windows"]) == 1
    assert state.attributes["expensive_windows"][0]["average_price"] == 0.5

    assert state.attributes["thresholds"] == {"cheap": 0.15, "expensive": 0.35, "solar_kwh": 1.0}

    slots = state.attributes["slots"]
    assert len(slots) == 96
    current_slot = slots[CHEAP_SLOT_1]
    assert current_slot["level"] == "cheap_solar"
    assert current_slot["in_cheapest_period"] is True
    assert current_slot["is_current"] is True
    assert slots[CHEAP_SLOT_2]["is_current"] is False


async def test_price_analysis_tomorrow_sensor_unavailable_without_tomorrow_data(
    hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
):
    """price_analysis_tomorrow is unavailable until tomorrow's prices exist, then reports them."""
    entry = await setup_price_analysis_entry(
        hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
    )

    assert state_for_key(hass, entry, "sensor", "price_analysis_tomorrow").state == "unavailable"


async def test_price_analysis_tomorrow_sensor_with_tomorrow_data(
    hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
):
    """price_analysis_tomorrow reports tomorrow's cheapest period once tomorrow's prices exist."""
    entry = await setup_price_analysis_entry(
        hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch, with_tomorrow=True
    )

    state = state_for_key(hass, entry, "sensor", "price_analysis_tomorrow")
    assert state.state != "unavailable"

    tomorrow_midnight = local_midnight() + timedelta(days=1)
    expected_start = tomorrow_midnight + timedelta(minutes=15 * 10)
    assert state.state == timestamp_state(expected_start)
    assert len(state.attributes["slots"]) == 96


async def test_next_cheapest_period_sensor(
    hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
):
    """next_cheapest_period reports the upcoming cheapest period's start/end/average_price/minutes."""
    entry = await setup_price_analysis_entry(
        hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
    )

    state = state_for_key(hass, entry, "sensor", "next_cheapest_period")

    expected_start = local_midnight() + timedelta(minutes=15 * CHEAP_SLOT_1)
    assert state.state == timestamp_state(expected_start)
    assert state.attributes["average_price"] == 0.1
    assert state.attributes["minutes"] == 30


async def test_next_cheapest_period_stays_stable_while_running(
    hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
):
    """next_cheapest_period keeps the same start/end while `now` is inside it, instead of drifting (W3).

    Without this, each quarter-hour refresh would drop the already-elapsed
    slot(s) at the window's start from consideration (`not_before` moves
    forward with `now`), shrinking and eventually replacing the reported
    window while it is still running.
    """
    entry = await setup_price_analysis_entry(
        hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
    )

    expected_start = local_midnight() + timedelta(minutes=15 * CHEAP_SLOT_1)
    state = state_for_key(hass, entry, "sensor", "next_cheapest_period")
    assert state.state == timestamp_state(expected_start)

    # Move to 10:15, still inside the 10:00-10:30 window, and let the
    # coordinator's quarter-hour timer trigger a refresh.
    freezer.move_to("2026-01-15 10:15:00+01:00")
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()

    state = state_for_key(hass, entry, "sensor", "next_cheapest_period")
    assert state.state == timestamp_state(expected_start)
    assert state.attributes["minutes"] == 30


async def test_options_flow_submit_keeps_next_cheapest_period_available(
    hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
):
    """Regression (C1): submitting the options flow must not break the analysis entities.

    `NumberSelector` always returns a float; without casting
    cheapest_period_minutes back to an int before saving, the stored float
    made `find_cheapest_period()` raise `TypeError` (a float used in
    `range()`/slicing), leaving `next_cheapest_period` (and the other
    analysis entities) permanently unavailable after any options save.
    """
    entry = await setup_price_analysis_entry(
        hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT,
            const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_PRICE_ANALYSIS],
        },
    )
    assert result2["step_id"] == "analysis"

    result3 = await hass.config_entries.options.async_configure(
        result2["flow_id"],
        {
            SECTION_PRICE_LEVELS: {
                const.CONF_CHEAP_PRICE_THRESHOLD: 0.15,
                const.CONF_EXPENSIVE_PRICE_THRESHOLD: 0.35,
                const.CONF_SOLAR_THRESHOLD_KWH: 1.0,
            },
            SECTION_CHEAPEST_PERIOD: {
                const.CONF_CHEAPEST_PERIOD_MINUTES: 30,
            },
        },
    )
    await hass.async_block_till_done()

    assert result3["type"] == "create_entry"
    assert entry.options[const.CONF_CHEAPEST_PERIOD_MINUTES] == 30
    assert isinstance(entry.options[const.CONF_CHEAPEST_PERIOD_MINUTES], int)

    state = state_for_key(hass, entry, "sensor", "next_cheapest_period")
    assert state is not None
    assert state.state != "unavailable"


async def test_next_cheapest_period_crosses_midnight(
    hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch
):
    """next_cheapest_period can span today's last slot and tomorrow's first slot(s)."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 23:50:00+01:00")

    electricity_today = [0.20] * 96
    electricity_today[95] = 0.05  # 23:45-00:00 local, the last slot of today

    electricity_tomorrow = [0.20] * 96
    electricity_tomorrow[0] = 0.05  # 00:00-00:15 local, the first slot of tomorrow

    install_prices(
        mock_frank_energie_class,
        electricity_today,
        [1.0] * 96,
        tomorrow_electricity=electricity_tomorrow,
        tomorrow_gas=[1.0] * 96,
        resolution_minutes=15,
    )

    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        options={
            const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT,
            const.CONF_CHEAP_PRICE_THRESHOLD: 0.15,
            const.CONF_EXPENSIVE_PRICE_THRESHOLD: 0.35,
            const.CONF_CHEAPEST_PERIOD_MINUTES: 30,
        },
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = state_for_key(hass, entry, "sensor", "next_cheapest_period")

    today_midnight = local_midnight()
    expected_start = today_midnight + timedelta(minutes=15 * 95)
    expected_end = today_midnight + timedelta(days=1, minutes=15)

    assert state.state == timestamp_state(expected_start)
    assert state.attributes["end"] == expected_end
    assert state.attributes["average_price"] == pytest.approx(0.05)
    assert state.attributes["minutes"] == 30


@pytest.mark.parametrize(
    "prices_timezone, expected_offset",
    [
        (const.PRICES_TIMEZONE_UTC, timedelta(0)),
        (const.PRICES_TIMEZONE_HOME_ASSISTANT, timedelta(hours=1)),
    ],
    ids=["utc", "home_assistant"],
)
async def test_price_analysis_today_attribute_times_follow_prices_timezone_option(
    hass, enable_custom_integrations, mock_frank_energie_class, freezer, monkeypatch, prices_timezone, expected_offset
):
    """The cheapest_period start/end in price_analysis_today's attributes follow prices_timezone.

    The frozen "now" (2026-01-15, Europe/Amsterdam) is in winter time (UTC+1),
    so "home_assistant" localizes to a +1h offset while "utc" stays at +0h,
    even though the underlying instant is identical either way.
    """
    entry = await setup_price_analysis_entry(
        hass,
        enable_custom_integrations,
        mock_frank_energie_class,
        freezer,
        monkeypatch,
        prices_timezone=prices_timezone,
    )

    state = state_for_key(hass, entry, "sensor", "price_analysis_today")

    expected_start = local_midnight() + timedelta(minutes=15 * CHEAP_SLOT_1)
    cheapest_period = state.attributes["cheapest_period"]

    assert cheapest_period["start"] == expected_start
    assert cheapest_period["start"].utcoffset() == expected_offset
