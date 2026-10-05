"""Tests for the Frank Energie integration setup (site discovery)."""
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.exceptions import AuthException, AuthRequiredException, NetworkError, RequestException
from python_frank_energie.models import DeliverySite

from custom_components.frank_energie import _async_setup_cost_data_sync, const
from custom_components.frank_energie.usage import UsageData
from tests.utils import (
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    build_market_prices,
    configure_authenticated_api as _configure_authenticated_api,
    make_delivery_site,
    make_energy_category,
    make_month_insights,
    make_month_summary,
    make_period_usage_and_costs,
    make_usage_item,
    make_user_sites,
)


@pytest.fixture
async def entry_with_token(hass, enable_custom_integrations):
    """Config entry that has an access token but no site_reference yet."""
    config_entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            CONF_ACCESS_TOKEN: FAKE_ACCESS_TOKEN,
            CONF_TOKEN: FAKE_REFRESH_TOKEN,
        },
        unique_id="frank_energie",
    )
    config_entry.add_to_hass(hass)
    return config_entry


async def test_site_discovery_picks_in_delivery_site_and_sets_title(
    hass, entry_with_token, mock_frank_energie_class
):
    """The first IN_DELIVERY site should be selected and used as the entry title."""
    sites = [
        make_delivery_site("ended-site", "DELIVERY_ENDED"),
        make_delivery_site("active-site", "IN_DELIVERY", street="Gustav Mahlerlaan", house_number="1025"),
    ]
    mock_frank_energie_class.UserSites.return_value = make_user_sites(sites)
    _configure_authenticated_api(mock_frank_energie_class)

    assert await hass.config_entries.async_setup(entry_with_token.entry_id)
    await hass.async_block_till_done()

    assert entry_with_token.state is ConfigEntryState.LOADED
    assert entry_with_token.data["site_reference"] == "active-site"
    assert entry_with_token.title == "Gustav Mahlerlaan 1025"


async def test_site_discovery_title_with_house_number_addition(
    hass, entry_with_token, mock_frank_energie_class
):
    """The title should include the house number addition when present."""
    sites = [make_delivery_site("active-site", "IN_DELIVERY", street="Kerkstraat", house_number="5", addition="A")]
    mock_frank_energie_class.UserSites.return_value = make_user_sites(sites)
    _configure_authenticated_api(mock_frank_energie_class)

    assert await hass.config_entries.async_setup(entry_with_token.entry_id)
    await hass.async_block_till_done()

    assert entry_with_token.title == "Kerkstraat 5 A"


async def test_site_discovery_no_address_keeps_title_unchanged(
    hass, entry_with_token, mock_frank_energie_class
):
    """When the delivery site has no address, the entry title should stay unchanged."""
    original_title = entry_with_token.title
    site = DeliverySite(
        addressHasMultipleSites=False,
        propositionType=None,
        reference="active-site",
        segments=["ELECTRICITY"],
        address=None,
        status="IN_DELIVERY",
        deliveryStartDate=None,
        deliveryEndDate=None,
        firstMeterReadingDate=None,
        lastMeterReadingDate=None,
    )
    mock_frank_energie_class.UserSites.return_value = make_user_sites([site])
    _configure_authenticated_api(mock_frank_energie_class)

    assert await hass.config_entries.async_setup(entry_with_token.entry_id)
    await hass.async_block_till_done()

    assert entry_with_token.title == original_title
    assert entry_with_token.data["site_reference"] == "active-site"


async def test_site_discovery_no_in_delivery_site_retries_setup(
    hass, entry_with_token, mock_frank_energie_class
):
    """No IN_DELIVERY site should cause ConfigEntryNotReady (SETUP_RETRY)."""
    sites = [make_delivery_site("ended-site", "DELIVERY_ENDED")]
    mock_frank_energie_class.UserSites.return_value = make_user_sites(sites)

    assert not await hass.config_entries.async_setup(entry_with_token.entry_id)
    await hass.async_block_till_done()

    assert entry_with_token.state is ConfigEntryState.SETUP_RETRY


async def test_site_discovery_request_exception_retries_setup(
    hass, entry_with_token, mock_frank_energie_class
):
    """UserSites raising a RequestException should cause ConfigEntryNotReady (SETUP_RETRY)."""
    mock_frank_energie_class.UserSites.side_effect = RequestException("boom")

    assert not await hass.config_entries.async_setup(entry_with_token.entry_id)
    await hass.async_block_till_done()

    assert entry_with_token.state is ConfigEntryState.SETUP_RETRY


async def test_setup_skips_discovery_when_site_reference_present(
    hass, config_entry, mock_frank_energie_class
):
    """When site_reference is already set, UserSites should not be called."""
    mock_frank_energie_class.is_authenticated = False
    mock_frank_energie_class.prices.return_value = build_market_prices(
        dt_util.now(), [0.2] * 24, [1.0] * 24
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    mock_frank_energie_class.UserSites.assert_not_awaited()


async def test_site_discovery_network_error_retries_setup(hass, entry_with_token, mock_frank_energie_class):
    """UserSites raising a NetworkError should cause ConfigEntryNotReady (SETUP_RETRY)."""
    mock_frank_energie_class.UserSites.side_effect = NetworkError("network unreachable")

    assert not await hass.config_entries.async_setup(entry_with_token.entry_id)
    await hass.async_block_till_done()

    assert entry_with_token.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize("exception_cls", [AuthException, AuthRequiredException])
async def test_site_discovery_auth_exception_starts_reauth(
    hass, entry_with_token, mock_frank_energie_class, exception_cls
):
    """UserSites raising AuthException/AuthRequiredException should trigger a reauth flow (SETUP_ERROR)."""
    mock_frank_energie_class.UserSites.side_effect = exception_cls("authentication required")

    assert not await hass.config_entries.async_setup(entry_with_token.entry_id)
    await hass.async_block_till_done()

    assert entry_with_token.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress()
    assert any(
        flow["context"].get("source") == "reauth" and flow["context"].get("entry_id") == entry_with_token.entry_id
        for flow in flows
    )


async def test_delivery_sites_skips_none_entries(hass, entry_with_token, mock_frank_energie_class):
    """A None entry in deliverySites should be skipped, and the valid IN_DELIVERY site picked."""
    valid_site = make_delivery_site("active-site", "IN_DELIVERY", street="Vondelstraat", house_number="7")
    user_sites = make_user_sites([valid_site])
    user_sites.deliverySites = [None, valid_site]
    mock_frank_energie_class.UserSites.return_value = user_sites
    _configure_authenticated_api(mock_frank_energie_class)

    assert await hass.config_entries.async_setup(entry_with_token.entry_id)
    await hass.async_block_till_done()

    assert entry_with_token.state is ConfigEntryState.LOADED
    assert entry_with_token.data["site_reference"] == "active-site"
    assert entry_with_token.title == "Vondelstraat 7"

M1 = datetime(2024, 1, 1, tzinfo=UTC)
M2 = datetime(2024, 1, 2, tzinfo=UTC)


def _sync_setup(frank_data, usage_data):
    """Run _async_setup_cost_data_sync with stub coordinators; return the listeners and mocks."""
    frank = MagicMock(data=frank_data)
    usage = MagicMock(data=usage_data)
    entry = MagicMock()
    entry.async_create_background_task.side_effect = lambda _hass, coro, _name: coro.close()
    start_import = MagicMock()
    frank.async_request_refresh = AsyncMock()
    usage.async_request_refresh = AsyncMock()
    _async_setup_cost_data_sync(MagicMock(), entry, frank, usage, start_import)
    on_frank = frank.async_add_listener.call_args[0][0]
    return frank, usage, on_frank, usage.async_add_listener.call_args[0][0], start_import


def _summary_data(day):
    return {const.DATA_MONTH_SUMMARY: make_month_summary(lastMeterReadingDate=day)}


def _usage_data(daily_date=None, monthly_date=None, gas_filled=False):
    gas = make_energy_category(1.0, 1.0, "m3", [make_usage_item(M1, M2, 1.0, 1.0, "m3")]) if gas_filled else None
    return UsageData(
        daily=make_period_usage_and_costs(gas=gas) if daily_date else None,
        daily_date=daily_date,
        monthly=make_month_insights(lastMeterReadingDate=monthly_date) if monthly_date else None,
    )


@pytest.mark.parametrize(
    "new_usage",
    [
        _usage_data(date(2024, 1, 2), M1),
        _usage_data(date(2024, 1, 1), M2),
        _usage_data(date(2024, 1, 1), M1, gas_filled=True),
    ],
    ids=["new_daily", "new_monthly", "gas_filled_same_day"],
)
async def test_cost_data_sync_new_value_refreshes_other_sources(new_usage):
    """A new month summary date refreshes usage; a new daily/monthly value refreshes the main coordinator."""
    frank, usage, on_frank, on_usage, start_import = _sync_setup(
        _summary_data("2024-01-01"), _usage_data(date(2024, 1, 1), M1)
    )

    frank.data = _summary_data("2024-01-02")
    on_frank()
    usage.async_request_refresh.assert_called_once()
    start_import.assert_called_once()

    usage.data = new_usage
    on_usage()
    frank.async_request_refresh.assert_called_once()
    assert start_import.call_count == 2


async def test_cost_data_sync_ignores_unchanged_and_none_markers():
    """Unchanged markers, markers turning None and returning to the old value trigger nothing."""
    frank, usage, on_frank, on_usage, start_import = _sync_setup(
        _summary_data("2024-01-01"), _usage_data(date(2024, 1, 1), M1)
    )

    for new_frank, new_usage in [
        (_summary_data("2024-01-01"), _usage_data(date(2024, 1, 1), M1)),
        ({const.DATA_MONTH_SUMMARY: None}, _usage_data()),
        (None, None),
        (_summary_data("2024-01-01"), _usage_data(date(2024, 1, 1), M1)),
    ]:
        frank.data, usage.data = new_frank, new_usage
        on_frank()
        on_usage()

    usage.async_request_refresh.assert_not_called()
    frank.async_request_refresh.assert_not_called()
    start_import.assert_not_called()
