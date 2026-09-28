"""Tests for the Frank Energie integration setup (site discovery)."""
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.exceptions import AuthException, AuthRequiredException, NetworkError, RequestException
from python_frank_energie.models import Address, DeliverySite, Invoices, MonthSummary, UserSites

from custom_components.frank_energie import const
from tests.utils import FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN, build_market_prices

pytestmark = pytest.mark.asyncio


def make_delivery_site(
    reference: str,
    status: str,
    street: str = "Teststraat",
    house_number: str = "12",
    addition: str | None = None,
) -> DeliverySite:
    address = Address(
        street=street,
        houseNumber=house_number,
        zipCode="1234 AB",
        city="Amsterdam",
        houseNumberAddition=addition,
    )
    return DeliverySite(
        addressHasMultipleSites=False,
        propositionType=None,
        reference=reference,
        segments=["ELECTRICITY", "GAS"],
        address=address,
        status=status,
        deliveryStartDate=None,
        deliveryEndDate=None,
        firstMeterReadingDate=None,
        lastMeterReadingDate=None,
    )


def make_user_sites(sites: list[DeliverySite]) -> UserSites:
    first = sites[0] if sites else None
    return UserSites(
        deliverySites=sites,
        addressFormatted="x",
        addressHasMultipleSites=False,
        deliveryEndDate=None,
        deliveryStartDate=None,
        firstMeterReadingDate=None,
        lastMeterReadingDate=None,
        propositionType=None,
        reference=first.reference if first else "",
        segments=[],
        status="IN_DELIVERY",
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


def _configure_authenticated_api(mock_api):
    """Set up mock_api with enough authenticated responses for a full setup."""
    mock_api.is_authenticated = True
    mock_api.user_country.return_value = AsyncMock(countryCode="NL")
    market_prices = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    mock_api.user_prices.return_value = market_prices
    mock_api.month_summary.return_value = MonthSummary(
        _id="1",
        actualCostsUntilLastMeterReadingDate=10.0,
        expectedCostsUntilLastMeterReadingDate=12.0,
        lastMeterReadingDate="2024-01-01",
        costs_per_day_till_now=1.0,
        meterReadingDayCompleteness=1.0,
        gasExcluded=False,
        typename="MonthSummary",
        expectedCosts=100.0,
    )
    mock_api.invoices.return_value = Invoices.empty()


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
