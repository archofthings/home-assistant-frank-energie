"""Tests for UsageCoordinator (see usage.py)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.exceptions import AuthException, AuthRequiredException, NetworkError

from custom_components.frank_energie import const
from custom_components.frank_energie.coordinator import FrankEnergieCoordinator
from custom_components.frank_energie.usage import UsageCoordinator, UsageData, usage_day_incomplete
from tests.utils import (
    make_energy_category,
    make_month_insights,
    make_period_usage_and_costs,
    make_usage_item,
)

# --------------------------------------------------------------------------
# UsageCoordinator: fetches yesterday (Amsterdam market day - 1) and the
# current month, only for the enabled groups.
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _freeze_midday(freezer):
    """Freeze time at midday UTC on 2026-01-15, so "yesterday" is 2026-01-14 in both UTC and Amsterdam time."""
    freezer.move_to("2026-01-15 12:00:00+00:00")


@pytest.fixture
def entry(hass):
    config_entry = MockConfigEntry(domain=const.DOMAIN, data={"site_reference": "site-1"}, unique_id="frank_energie")
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
def price_coordinator(mock_api):
    """A stand-in for FrankEnergieCoordinator exposing only what UsageCoordinator needs."""
    coordinator = MagicMock()
    coordinator.api = mock_api
    coordinator.site_reference = "site-1"
    return coordinator


@pytest.fixture
def coordinator(hass, entry, price_coordinator):
    return UsageCoordinator(
        hass, entry, price_coordinator, {const.SENSOR_GROUP_DAILY_USAGE, const.SENSOR_GROUP_MONTHLY_USAGE}
    )


async def test_fetches_yesterday_and_current_month_for_both_groups(coordinator, mock_api):
    """Both daily and monthly are fetched, with the correct site_reference and date, when both groups are enabled."""
    mock_api.period_usage_and_costs.return_value = make_period_usage_and_costs()
    mock_api.month_insights.return_value = make_month_insights()

    data = await coordinator._async_update_data()

    mock_api.period_usage_and_costs.assert_awaited_once_with("site-1", "2026-01-14")
    mock_api.month_insights.assert_awaited_once_with("site-1", "2026-01")
    assert data.daily_date == date(2026, 1, 14)


async def test_yesterday_follows_amsterdam_date_not_utc_date_at_midnight_boundary(coordinator, mock_api, freezer):
    """At 00:30 Europe/Amsterdam (23:30 UTC the day before, winter time), yesterday is the Amsterdam date - 1."""
    freezer.move_to("2026-01-14 23:30:00+00:00")
    mock_api.period_usage_and_costs.return_value = make_period_usage_and_costs()
    mock_api.month_insights.return_value = make_month_insights()

    data = await coordinator._async_update_data()

    mock_api.period_usage_and_costs.assert_awaited_once_with("site-1", "2026-01-14")
    assert data.daily_date == date(2026, 1, 14)


@pytest.mark.parametrize(
    "groups, expect_daily, expect_monthly",
    [
        ({const.SENSOR_GROUP_DAILY_USAGE}, True, False),
        ({const.SENSOR_GROUP_MONTHLY_USAGE}, False, True),
    ],
    ids=["daily_only", "monthly_only"],
)
async def test_fetches_only_the_enabled_groups(
    hass, entry, price_coordinator, mock_api, groups, expect_daily, expect_monthly
):
    """Only the API call(s) for the enabled group(s) are made."""
    mock_api.period_usage_and_costs.return_value = make_period_usage_and_costs()
    mock_api.month_insights.return_value = make_month_insights()
    only_coordinator = UsageCoordinator(hass, entry, price_coordinator, groups)

    data = await only_coordinator._async_update_data()

    assert mock_api.period_usage_and_costs.called is expect_daily
    assert mock_api.month_insights.called is expect_monthly
    assert (data.daily is not None) is expect_daily
    assert (data.monthly is not None) is expect_monthly


# --------------------------------------------------------------------------
# Error handling: NetworkError/ValueError with previous data keeps it,
# without previous data raises UpdateFailed; an auth error always raises
# UpdateFailed (never ConfigEntryAuthFailed), leaving reauth to the main
# coordinator's own update cycle.
# --------------------------------------------------------------------------

_OTHER_ERRORS = pytest.mark.parametrize(
    "make_exception",
    [lambda: NetworkError("network unreachable"), lambda: ValueError("could not parse response")],
    ids=["network_error", "value_error"],
)


@_OTHER_ERRORS
async def test_other_error_without_previous_data_raises_update_failed(coordinator, mock_api, make_exception):
    mock_api.period_usage_and_costs.side_effect = make_exception()
    mock_api.month_insights.side_effect = make_exception()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@_OTHER_ERRORS
async def test_other_error_with_previous_data_keeps_it(coordinator, mock_api, make_exception):
    stale = UsageData(daily=make_period_usage_and_costs(), daily_date=date(2026, 1, 13), monthly=None)
    coordinator.data = stale
    mock_api.period_usage_and_costs.side_effect = make_exception()
    mock_api.month_insights.side_effect = make_exception()

    data = await coordinator._async_update_data()

    assert data == stale


async def test_daily_failure_keeps_previous_daily_with_its_date_and_fresh_monthly(coordinator, mock_api):
    """One failing part uses its previous value (and daily_date) while the other part is still updated."""
    stale = UsageData(daily=make_period_usage_and_costs(), daily_date=date(2026, 1, 13), monthly=None)
    coordinator.data = stale
    monthly = make_month_insights()
    mock_api.period_usage_and_costs.side_effect = NetworkError("timeout")
    mock_api.month_insights.return_value = monthly

    data = await coordinator._async_update_data()

    assert data == UsageData(daily=stale.daily, daily_date=date(2026, 1, 13), monthly=monthly)


@pytest.mark.parametrize(
    "failure_time, keeps_monthly",
    [("2026-01-20 12:00:00+00:00", True), ("2026-02-01 12:00:00+00:00", False)],
    ids=["same_month", "new_month"],
)
async def test_monthly_failure_keeps_previous_monthly_only_within_the_same_month(
    coordinator, mock_api, freezer, failure_time, keeps_monthly
):
    """A failed monthly fetch keeps the previous monthly data, but never shows last month's data as this month's."""
    monthly = make_month_insights()
    mock_api.period_usage_and_costs.return_value = make_period_usage_and_costs()
    mock_api.month_insights.return_value = monthly
    coordinator.data = await coordinator._async_update_data()

    freezer.move_to(failure_time)
    mock_api.month_insights.side_effect = ValueError("Could not find a first or last meter reading")
    data = await coordinator._async_update_data()

    assert data.daily is not None
    assert data.monthly == (monthly if keeps_monthly else None)


@pytest.mark.parametrize(
    "exc_cls", [AuthException, AuthRequiredException], ids=["auth_exception", "auth_required_exception"]
)
async def test_auth_error_raises_update_failed_not_config_entry_auth_failed(coordinator, mock_api, exc_cls):
    """An auth error raises UpdateFailed, not ConfigEntryAuthFailed: reauth is left to the main coordinator."""
    mock_api.period_usage_and_costs.side_effect = exc_cls("token expired")

    with pytest.raises(UpdateFailed) as excinfo:
        await coordinator._async_update_data()

    assert not isinstance(excinfo.value, ConfigEntryAuthFailed)


# --------------------------------------------------------------------------
# Tokens renewed transparently inside a usage call are persisted right away,
# via the price coordinator's own persistence helper.
# --------------------------------------------------------------------------


async def test_tokens_renewed_during_refresh_are_persisted(hass, entry, mock_api):
    """api._auth set to new tokens during a usage refresh ends up in entry.data afterwards."""
    price_coordinator = FrankEnergieCoordinator(hass, entry, mock_api)
    usage_coordinator = UsageCoordinator(
        hass, entry, price_coordinator, {const.SENSOR_GROUP_DAILY_USAGE, const.SENSOR_GROUP_MONTHLY_USAGE}
    )
    mock_api.is_authenticated = True
    mock_api.period_usage_and_costs.return_value = make_period_usage_and_costs()
    mock_api.month_insights.return_value = make_month_insights()

    renewed = MagicMock()
    renewed.authToken = "new-access-token"
    renewed.refreshToken = "new-refresh-token"
    mock_api._auth = renewed

    await usage_coordinator._async_update_data()

    assert entry.data[CONF_ACCESS_TOKEN] == "new-access-token"
    assert entry.data[CONF_TOKEN] == "new-refresh-token"


def _category(filled: bool = True, costs_total: float | None = 1.0):
    items = [make_usage_item(datetime(2026, 1, 14, tzinfo=timezone.utc), datetime(2026, 1, 14, 1, tzinfo=timezone.utc),
                             1.0, 1.0)] if filled else []
    return make_energy_category(1.0 if filled else 0.0, costs_total if filled else None, "kWh", items)


@pytest.mark.parametrize(
    ("data", "incomplete"),
    [
        (None, True),
        (make_period_usage_and_costs(electricity=_category(), gas=_category()), False),
        (make_period_usage_and_costs(electricity=_category(), gas=_category(False)), True),
        (make_period_usage_and_costs(electricity=_category(), gas=None), False),
        (make_period_usage_and_costs(electricity=_category(False), gas=_category()), True),
        (make_period_usage_and_costs(electricity=_category(), gas=_category(costs_total=None)), True),
    ],
    ids=["none", "complete", "gas_empty", "no_gas", "electricity_empty", "gas_costs_missing"],
)
def test_usage_day_incomplete(data, incomplete):
    assert usage_day_incomplete(data) is incomplete


async def test_update_interval_retries_hourly_while_gas_is_empty(coordinator, mock_api):
    """An incomplete day shortens the interval to 1 hour; a complete day restores 3 hours."""
    mock_api.month_insights.return_value = make_month_insights()
    mock_api.period_usage_and_costs.return_value = make_period_usage_and_costs(
        electricity=_category(), gas=_category(False)
    )
    await coordinator._async_update_data()
    assert coordinator.update_interval == timedelta(hours=1)

    mock_api.period_usage_and_costs.return_value = make_period_usage_and_costs(
        electricity=_category(), gas=_category()
    )
    await coordinator._async_update_data()
    assert coordinator.update_interval == timedelta(hours=3)
