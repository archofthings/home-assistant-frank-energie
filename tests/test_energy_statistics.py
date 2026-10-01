"""Tests for the Energy dashboard statistics import (see energy_statistics.py)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done
from python_frank_energie.exceptions import FrankEnergieException

from custom_components.frank_energie import const, energy_statistics
from custom_components.frank_energie.energy_statistics import FrankEnergieStatisticsImporter
from tests.utils import (
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    build_market_prices,
    local_midnight,
    make_energy_category,
    make_me,
    make_period_usage_and_costs,
    make_usage_item,
)

ELEC_ID = "frank_energie:electricity_usage_site_1"


@pytest.fixture(autouse=True)
def _freeze_midday(freezer):
    """Midday UTC on 2026-01-15: yesterday is 2026-01-14 in Amsterdam."""
    freezer.move_to("2026-01-15 12:00:00+00:00")


def day_data(day: str, usage: float = 1.0, gas: bool = True):
    """A full Amsterdam day (24 hourly items, +01:00) for electricity, feed-in and optionally gas."""
    start = datetime.fromisoformat(f"{day}T00:00:00+01:00")

    def category(unit):
        items = [
            make_usage_item(start + timedelta(hours=h), start + timedelta(hours=h + 1), usage, usage / 2, unit)
            for h in range(24)
        ]
        return make_energy_category(usage * 24, usage * 12, unit, items)

    return make_period_usage_and_costs(
        electricity=category("kWh"), feed_in=category("kWh"), gas=category("m3") if gas else None
    )


@pytest.fixture(autouse=True)
def sleep_mock():
    """Replace the module's asyncio.sleep (the pacing between fetches) so tests don't wait."""
    sleep = AsyncMock()
    with patch.object(energy_statistics, "asyncio", SimpleNamespace(sleep=sleep, Lock=asyncio.Lock)):
        yield sleep


@pytest.fixture
def importer(hass, mock_api):
    entry = MockConfigEntry(domain=const.DOMAIN, data={"site_reference": "site-1"}, title="Home")
    price_coordinator = MagicMock()
    price_coordinator.api = mock_api
    price_coordinator.site_reference = "site-1"
    mock_api.period_usage_and_costs.side_effect = lambda site, day: day_data(day)
    return FrankEnergieStatisticsImporter(hass, entry, price_coordinator)


async def read_stats(hass, statistic_id):
    await async_wait_recording_done(hass)
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        None,
        {statistic_id},
        "hour",
        None,
        {"state", "sum"},
    )
    return result.get(statistic_id, [])


async def test_first_run_imports_30_days_then_later_run_reimports_last_two_days(
    recorder_mock, hass, importer, mock_api, freezer, sleep_mock
):
    """First run: 30 days, all statistics. Next day: only the last 2 days, corrections replace instead of adding."""
    await importer.async_import()
    # Paced between the 30 calls (not before the first); the short run below (3 days) is not paced.
    assert sleep_mock.await_count == 29
    sleep_mock.assert_awaited_with(energy_statistics.FETCH_PAUSE_SECONDS)

    dates = [c.args[1] for c in mock_api.period_usage_and_costs.await_args_list]
    assert len(dates) == 30
    assert dates[0] == "2025-12-16" and dates[-1] == "2026-01-14"
    rows = await read_stats(hass, ELEC_ID)
    assert len(rows) == 30 * 24
    assert rows[-1]["sum"] == pytest.approx(30 * 24)
    for kind in ("electricity_costs", "feed_in", "feed_in_revenue", "gas_usage", "gas_costs"):
        assert len(await read_stats(hass, f"frank_energie:{kind}_site_1")) == 30 * 24

    # Next day: last stored day 01-14 -> start 01-13, yesterday 01-15. 01-14 has a corrected value.
    freezer.move_to("2026-01-16 12:00:00+00:00")
    mock_api.period_usage_and_costs.reset_mock()
    mock_api.period_usage_and_costs.side_effect = lambda site, day: day_data(day, 2.0 if day == "2026-01-14" else 1.0)
    await importer.async_import()

    dates = [c.args[1] for c in mock_api.period_usage_and_costs.await_args_list]
    assert dates == ["2026-01-13", "2026-01-14", "2026-01-15"]
    assert sleep_mock.await_count == 29
    rows = await read_stats(hass, ELEC_ID)
    assert len(rows) == 31 * 24
    # 28 old days (1 kWh/h) + corrected 01-13 (1) + 01-14 (2) + 01-15 (1)
    assert rows[-1]["sum"] == pytest.approx(28 * 24 + 24 + 48 + 24)


def test_hourly_values_sums_15_minute_items_into_one_hour():
    """Four quarter-hour items in the same UTC hour become a single hourly row."""
    start = datetime(2026, 1, 14, 0, 0, tzinfo=timezone.utc)
    items = [
        make_usage_item(start + timedelta(minutes=15 * i), start + timedelta(minutes=15 * (i + 1)), 0.25, 0.1)
        for i in range(4)
    ]
    day = make_period_usage_and_costs(electricity=make_energy_category(1.0, 0.4, "kWh", items))

    hourly = FrankEnergieStatisticsImporter._hourly_values([day], "electricity", "usage")

    assert hourly == {start: pytest.approx(1.0)}


async def test_error_stops_run_keeping_earlier_days_and_missing_gas_creates_no_gas_statistics(
    recorder_mock, hass, importer, mock_api
):
    """A failing day mid-run does not raise; earlier days are imported. A response without gas skips gas."""
    def fetch(site, day):
        if day == "2025-12-19":
            raise FrankEnergieException("boom")
        return day_data(day, gas=False)

    mock_api.period_usage_and_costs.side_effect = fetch
    await importer.async_import()

    assert mock_api.period_usage_and_costs.await_count == 4
    assert len(await read_stats(hass, ELEC_ID)) == 3 * 24
    assert await read_stats(hass, "frank_energie:gas_usage_site_1") == []
    assert await read_stats(hass, "frank_energie:gas_costs_site_1") == []


@pytest.mark.parametrize("enabled", [True, False])
async def test_setup_starts_import_only_when_group_enabled(
    hass, enable_custom_integrations, mock_frank_energie_class, enabled
):
    """The importer is created and run only for an authenticated entry with the energy_statistics group."""
    groups = [const.SENSOR_GROUP_ENERGY_STATISTICS] if enabled else [const.SENSOR_GROUP_DAILY_STATISTICS]
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1", CONF_ACCESS_TOKEN: FAKE_ACCESS_TOKEN, CONF_TOKEN: FAKE_REFRESH_TOKEN},
        options={const.CONF_SENSOR_GROUPS: groups},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    mock_frank_energie_class.is_authenticated = True
    mock_frank_energie_class.user_country.return_value = make_me("NL")
    mock_frank_energie_class.user_prices.return_value = build_market_prices(local_midnight(), [0.2] * 4, [1.0] * 4)

    with patch("custom_components.frank_energie.FrankEnergieStatisticsImporter") as importer_cls:
        importer_cls.return_value.async_import = AsyncMock(return_value=None)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert importer_cls.called is enabled
    mock_frank_energie_class.period_usage_and_costs.assert_not_awaited()


async def test_leading_empty_days_are_skipped_and_empty_yesterday_stops_without_error(
    recorder_mock, hass, importer, mock_api
):
    """Old empty days are skipped (statistics start at day 6); an empty yesterday stops the run quietly."""
    def fetch(site, day):
        if day < "2025-12-21" or day == "2026-01-14":
            return None
        return day_data(day)

    mock_api.period_usage_and_costs.side_effect = fetch
    await importer.async_import()

    assert mock_api.period_usage_and_costs.await_count == 30
    rows = await read_stats(hass, ELEC_ID)
    assert len(rows) == 24 * 24
    assert dt_util.utc_from_timestamp(rows[0]["start"]) == datetime(2025, 12, 20, 23, tzinfo=timezone.utc)


async def test_no_import_during_maintenance_window(recorder_mock, hass, importer, mock_api, freezer):
    """Between 00:00 and 01:00 UTC the API is not called."""
    freezer.move_to("2026-01-15 00:30:00+00:00")
    await importer.async_import()
    mock_api.period_usage_and_costs.assert_not_awaited()
