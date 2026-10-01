"""Tests for the daily and monthly usage and costs sensors (see sensor.py)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.exceptions import FrankEnergieException

from custom_components.frank_energie import const
from tests.utils import (
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    build_market_prices,
    make_difference,
    make_energy_category,
    make_me,
    make_month_insights,
    make_period_usage_and_costs,
    make_usage_item,
)

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def entity_id_for_key(hass, entry, key: str) -> str | None:
    """Look up an entity_id by its unique_id (f'{entry.unique_id}.{key}'), independent of slugging."""
    return er.async_get(hass).async_get_entity_id("sensor", const.DOMAIN, f"{entry.unique_id}.{key}")


def state_for_key(hass, entry, key: str):
    """Return the current state object for a sensor by its description key."""
    entity_id = entity_id_for_key(hass, entry, key)
    return hass.states.get(entity_id) if entity_id else None


def setup_authenticated_entry(hass, mock_frank_energie_class, groups: list[str]) -> MockConfigEntry:
    """Add and return an authenticated config entry with the given sensor_groups, ready for async_setup."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-1",
            CONF_ACCESS_TOKEN: FAKE_ACCESS_TOKEN,
            CONF_TOKEN: FAKE_REFRESH_TOKEN,
        },
        options={const.CONF_SENSOR_GROUPS: groups},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    mock_frank_energie_class.is_authenticated = True
    mock_frank_energie_class.user_country.return_value = make_me("NL")
    mock_frank_energie_class.user_prices.return_value = build_market_prices(dt_util.now(), [0.2] * 4, [1.0] * 4)
    return entry


@pytest.fixture(autouse=True)
def _freeze_midday(freezer):
    """Freeze time at midday UTC on 2026-01-15, so "yesterday" is 2026-01-14 in both UTC and Amsterdam time."""
    freezer.move_to("2026-01-15 12:00:00+00:00")


async def test_monthly_failure_keeps_daily_data(hass, enable_custom_integrations, mock_frank_energie_class):
    """Regression: on the 1st month_insights fails; yesterday's daily usage is still reported (no UpdateFailed)."""
    entry = setup_authenticated_entry(
        hass, mock_frank_energie_class, [const.SENSOR_GROUP_DAILY_USAGE, const.SENSOR_GROUP_MONTHLY_USAGE]
    )
    item_start = datetime(2026, 1, 14, 10, 0, tzinfo=timezone.utc)
    item = make_usage_item(item_start, item_start + timedelta(hours=1), usage=2.5, costs=0.6)
    mock_frank_energie_class.period_usage_and_costs.return_value = make_period_usage_and_costs(
        electricity=make_energy_category(10.0, 2.5, "kWh", items=[item]), gas=None, feed_in=None
    )
    mock_frank_energie_class.month_insights.side_effect = FrankEnergieException("no meter reading")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert float(state_for_key(hass, entry, "elec_usage_yesterday").state) == 10.0
    assert state_for_key(hass, entry, "elec_usage_month").state == "unavailable"


# --------------------------------------------------------------------------
# Daily sensors: state, unit, last_reset, date, hours; gas sensors are only
# created when the daily data actually has gas.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prices_timezone_option, expected_tz",
    [
        (None, timezone.utc),
        (const.PRICES_TIMEZONE_HOME_ASSISTANT, dt_util.get_time_zone("Europe/Amsterdam")),
    ],
    ids=["default_utc", "home_assistant_option"],
)
async def test_daily_sensors_state_unit_last_reset_date_and_hours(
    hass, enable_custom_integrations, mock_frank_energie_class, prices_timezone_option, expected_tz
):
    """The daily sensors report yesterday's totals, with date/hours attributes and a local-midnight last_reset;
    the "hours" from/till times follow the prices_timezone option."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    entry = setup_authenticated_entry(hass, mock_frank_energie_class, [const.SENSOR_GROUP_DAILY_USAGE])
    if prices_timezone_option is not None:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, const.CONF_PRICES_TIMEZONE: prices_timezone_option}
        )

    item_start = datetime(2026, 1, 14, 10, 0, tzinfo=timezone.utc)
    item_end = item_start + timedelta(hours=1)
    item = make_usage_item(item_start, item_end, usage=2.5, costs=0.6)
    electricity = make_energy_category(10.0, 2.5, "kWh", items=[item])
    mock_frank_energie_class.period_usage_and_costs.return_value = make_period_usage_and_costs(
        electricity=electricity, gas=None, feed_in=None
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    usage_state = state_for_key(hass, entry, "elec_usage_yesterday")
    costs_state = state_for_key(hass, entry, "elec_costs_yesterday")

    assert float(usage_state.state) == 10.0
    assert usage_state.attributes["unit_of_measurement"] == "kWh"
    assert usage_state.attributes["date"] == "2026-01-14"
    assert usage_state.attributes["hours"] == [
        {
            "from": item_start.astimezone(expected_tz),
            "till": item_end.astimezone(expected_tz),
            "usage": 2.5,
            "costs": 0.6,
        }
    ]
    assert usage_state.attributes["last_reset"] == dt_util.start_of_local_day(date(2026, 1, 14)).isoformat()

    assert float(costs_state.state) == 2.5
    assert costs_state.attributes["unit_of_measurement"] == "€"

    # Gas has no data for this account: gas sensors are not created.
    assert entity_id_for_key(hass, entry, "gas_usage_yesterday") is None
    assert entity_id_for_key(hass, entry, "gas_costs_yesterday") is None


async def test_daily_gas_sensors_created_when_gas_data_present(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """Gas usage/costs sensors are created (and report their totals) when the daily data has a gas category."""
    entry = setup_authenticated_entry(hass, mock_frank_energie_class, [const.SENSOR_GROUP_DAILY_USAGE])
    mock_frank_energie_class.period_usage_and_costs.return_value = make_period_usage_and_costs(
        electricity=make_energy_category(10.0, 2.5),
        gas=make_energy_category(5.0, 3.0, "m3"),
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    gas_usage_state = state_for_key(hass, entry, "gas_usage_yesterday")
    assert gas_usage_state is not None
    assert float(gas_usage_state.state) == 5.0


async def test_daily_gas_sensors_created_when_gas_not_yet_published(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """When yesterday's electricity AND gas are both None (data not published yet), gas sensors are still created,
    unlike the "no gas at all" case where electricity is present and gas is None."""
    entry = setup_authenticated_entry(hass, mock_frank_energie_class, [const.SENSOR_GROUP_DAILY_USAGE])
    mock_frank_energie_class.period_usage_and_costs.return_value = make_period_usage_and_costs(
        electricity=None, gas=None, feed_in=None
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_id_for_key(hass, entry, "gas_usage_yesterday") is not None
    assert entity_id_for_key(hass, entry, "gas_costs_yesterday") is not None


# --------------------------------------------------------------------------
# Monthly sensors: state and attributes.
# --------------------------------------------------------------------------


async def test_monthly_sensors_state_and_attributes(hass, enable_custom_integrations, mock_frank_energie_class):
    """The monthly sensors report month_insights' actual values, with expected/average-price attributes."""
    entry = setup_authenticated_entry(hass, mock_frank_energie_class, [const.SENSOR_GROUP_MONTHLY_USAGE])
    last_meter_reading = datetime(2026, 1, 10, tzinfo=timezone.utc)
    mock_frank_energie_class.month_insights.return_value = make_month_insights(
        lastMeterReadingDate=last_meter_reading,
        expectedCostsFixed=15.0,
        electricityDifference=make_difference(
            actualUsage=120.0, actualCosts=30.0, actualAverageUnitPrice=0.25, expectedUsage=110.0, expectedCosts=28.0
        ),
        gasExcluded=True,
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    usage_state = state_for_key(hass, entry, "elec_usage_month")
    costs_state = state_for_key(hass, entry, "elec_costs_month")
    fixed_state = state_for_key(hass, entry, "fixed_costs_month")

    assert float(usage_state.state) == 120.0
    assert usage_state.attributes["expected_usage"] == 110.0
    assert usage_state.attributes["last_meter_reading"] == last_meter_reading

    assert float(costs_state.state) == 30.0
    assert costs_state.attributes["expected_costs"] == 28.0
    assert costs_state.attributes["average_price"] == 0.25

    assert float(fixed_state.state) == 15.0

    # gasExcluded=True: gas monthly sensors are not created.
    assert entity_id_for_key(hass, entry, "gas_usage_month") is None
    assert entity_id_for_key(hass, entry, "gas_costs_month") is None


async def test_monthly_feed_in_is_reported_positive(hass, enable_custom_integrations, mock_frank_energie_class):
    """Regression: month_insights reports feed-in as negative numbers; the sensors show them positive.

    Values taken from a live account: the daily sensors (period_usage_and_costs)
    already report feed-in and its revenue as positive, so without the sign flip
    the monthly feed-in showed "-39.443 kWh" and "-6.19 €".
    """
    entry = setup_authenticated_entry(hass, mock_frank_energie_class, [const.SENSOR_GROUP_MONTHLY_USAGE])
    mock_frank_energie_class.month_insights.return_value = make_month_insights(
        feedInDifference=make_difference(
            actualUsage=-39.443, expectedUsage=-238.9333, actualCosts=-6.19, expectedCosts=-24.11,
            actualAverageUnitPrice=0.157,
        ),
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    usage_state = state_for_key(hass, entry, "feed_in_month")
    revenue_state = state_for_key(hass, entry, "feed_in_revenue_month")

    assert float(usage_state.state) == 39.443
    assert usage_state.attributes["expected_usage"] == 238.9333
    assert float(revenue_state.state) == 6.19
    assert revenue_state.attributes["expected_costs"] == 24.11
    assert revenue_state.attributes["average_price"] == 0.157


async def test_monthly_last_reset_is_month_start_and_fixed_costs_has_no_state_class(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """Monthly usage/costs sensors report a last_reset at the start of the current month (Europe/Amsterdam), so
    statistics don't go negative on the 1st; fixed_costs_month is an expected/forecast value and has no
    state_class."""
    entry = setup_authenticated_entry(hass, mock_frank_energie_class, [const.SENSOR_GROUP_MONTHLY_USAGE])
    mock_frank_energie_class.month_insights.return_value = make_month_insights()

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    usage_state = state_for_key(hass, entry, "elec_usage_month")
    fixed_state = state_for_key(hass, entry, "fixed_costs_month")

    expected_last_reset = datetime(2026, 1, 1, tzinfo=dt_util.get_time_zone("Europe/Amsterdam"))
    assert usage_state.attributes["last_reset"] == expected_last_reset.isoformat()
    assert "state_class" not in fixed_state.attributes
