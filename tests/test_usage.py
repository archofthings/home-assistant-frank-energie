"""Tests for UsageCoordinator (see usage.py)."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.exceptions import AuthException, AuthRequiredException, NetworkError

from custom_components.frank_energie import const
from custom_components.frank_energie.usage import UsageCoordinator, UsageData
from tests.utils import make_month_insights, make_period_usage_and_costs

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

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@_OTHER_ERRORS
async def test_other_error_with_previous_data_keeps_it(coordinator, mock_api, make_exception):
    stale = UsageData(daily=make_period_usage_and_costs(), daily_date=date(2026, 1, 13), monthly=None)
    coordinator.data = stale
    mock_api.period_usage_and_costs.side_effect = make_exception()

    data = await coordinator._async_update_data()

    assert data is stale


@pytest.mark.parametrize(
    "exc_cls", [AuthException, AuthRequiredException], ids=["auth_exception", "auth_required_exception"]
)
async def test_auth_error_raises_update_failed_not_config_entry_auth_failed(coordinator, mock_api, exc_cls):
    """An auth error raises UpdateFailed, not ConfigEntryAuthFailed: reauth is left to the main coordinator."""
    mock_api.period_usage_and_costs.side_effect = exc_cls("token expired")

    with pytest.raises(UpdateFailed) as excinfo:
        await coordinator._async_update_data()

    assert not isinstance(excinfo.value, ConfigEntryAuthFailed)
