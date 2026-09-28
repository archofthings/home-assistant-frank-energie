"""Tests for FrankEnergieCoordinator."""
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.exceptions import AuthException, NoMarketPricesAvailableException, RequestException
from python_frank_energie.models import Invoices, Me, MonthSummary

from custom_components.frank_energie import const
from custom_components.frank_energie.coordinator import FrankEnergieCoordinator
from tests.utils import build_market_prices, build_price_data

pytestmark = pytest.mark.asyncio


def make_me(country_code: str = "NL") -> Me:
    """Build a minimal Me instance."""
    return Me(
        id="user-1",
        email="user@example.com",
        countryCode=country_code,
        advancedPaymentAmount=0.0,
        treesCount=0,
        hasInviteLink=False,
        InviteLinkUser=None,
        hasCO2Compensation=False,
        createdAt="2024-01-01T00:00:00Z",
        updatedAt="2024-01-01T00:00:00Z",
        addressHasMultipleSites=False,
        meterReadingExportPeriods=[],
        smartCharging={},
    )


def make_month_summary() -> MonthSummary:
    return MonthSummary(
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


@pytest.fixture
async def entry(hass):
    config_entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1", CONF_USERNAME: "someuser"},
        unique_id="frank_energie",
    )
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
def api():
    mock = AsyncMock()
    mock.is_authenticated = False
    # The coordinator reads api._auth (see _async_persist_tokens); default it
    # to None like a real, non-renewed FrankEnergie client so tests that don't
    # care about token persistence don't accidentally write Mock objects into
    # the config entry.
    mock._auth = None
    return mock


@pytest.fixture
def coordinator(hass, entry, api):
    return FrankEnergieCoordinator(hass, entry, api)


async def test_unauthenticated_fetches_today_and_tomorrow(coordinator, api):
    """Unauthenticated coordinator should fetch public prices for today and tomorrow."""
    today = dt_util.now().date()
    tomorrow = today + timedelta(days=1)

    today_prices = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    tomorrow_prices = build_market_prices(dt_util.now() + timedelta(days=1), [0.3] * 24, [1.1] * 24)

    async def prices_side_effect(start_date, resolution="PT15M"):
        if start_date == today:
            return today_prices
        if start_date == tomorrow:
            return tomorrow_prices
        raise AssertionError(f"Unexpected date {start_date}")

    api.prices.side_effect = prices_side_effect

    data = await coordinator._async_update_data()

    assert api.prices.await_count == 2
    assert api.user_prices.await_count == 0
    assert len(data[const.DATA_ELECTRICITY].all) == 48
    assert len(data[const.DATA_GAS].all) == 48
    assert data[const.DATA_MONTH_SUMMARY] is None
    assert data[const.DATA_INVOICES] is None
    api.month_summary.assert_not_awaited()
    api.invoices.assert_not_awaited()


async def test_authenticated_uses_user_prices_and_caches_country(coordinator, api):
    """Authenticated coordinator uses user_prices and fetches user_country only once."""
    api.is_authenticated = True
    api.user_country.return_value = make_me("BE")
    market_prices = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    api.user_prices.return_value = market_prices
    api.month_summary.return_value = make_month_summary()
    api.invoices.return_value = Invoices.empty()

    await coordinator._async_update_data()
    await coordinator._async_update_data()

    assert api.user_country.await_count == 1
    assert api.user_prices.await_count == 4  # today + tomorrow, twice
    for call in api.user_prices.await_args_list:
        assert call.args[1] == "BE"


async def test_user_country_empty_falls_back_to_nl(coordinator, api):
    """An empty/None countryCode from the API should fall back to 'NL'."""
    api.is_authenticated = True
    api.user_country.return_value = make_me("")
    api.user_prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    api.month_summary.return_value = None
    api.invoices.return_value = None

    await coordinator._async_update_data()

    assert api.user_prices.await_args_list[0].args[1] == "NL"


async def test_per_segment_fallback_to_public_prices(coordinator, api):
    """When user gas or electricity prices are empty, fall back to public prices for that segment."""
    api.is_authenticated = True
    api.user_country.return_value = make_me("NL")

    # Fresh objects per call so mutating one date's result (gas fallback) can't
    # leak into the other date's result via a shared mock return value.
    api.user_prices.side_effect = lambda *a, **k: build_market_prices(dt_util.now(), [0.2] * 24, [])
    api.prices.side_effect = lambda *a, **k: build_market_prices(dt_util.now(), [0.99] * 24, [1.5] * 24)
    api.month_summary.return_value = None
    api.invoices.return_value = None

    data = await coordinator._async_update_data()

    # Electricity came from user prices (0.2), gas fell back to public prices (1.5)
    assert data[const.DATA_ELECTRICITY].all[0].total == pytest.approx(0.2)
    assert data[const.DATA_GAS].all[0].total == pytest.approx(1.5)
    assert api.prices.await_count == 2


async def test_tomorrow_no_market_prices_is_not_fatal(coordinator, api):
    """NoMarketPricesAvailableException for tomorrow should not fail the update."""
    today_prices = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)

    async def prices_side_effect(start_date, resolution="PT15M"):
        if start_date == dt_util.now().date():
            return today_prices
        raise NoMarketPricesAvailableException("No market prices for tomorrow")

    api.prices.side_effect = prices_side_effect

    data = await coordinator._async_update_data()

    assert len(data[const.DATA_ELECTRICITY].all) == 24
    assert len(data[const.DATA_GAS].all) == 24


async def test_tomorrow_empty_pricedata_returns_today_unmerged(coordinator, api):
    """An empty (but not raising) tomorrow PriceData should not cause a merge/ValueError."""
    today_prices = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    empty_tomorrow = build_market_prices(dt_util.now() + timedelta(days=1), [], [])

    async def prices_side_effect(start_date, resolution="PT15M"):
        if start_date == dt_util.now().date():
            return today_prices
        return empty_tomorrow

    api.prices.side_effect = prices_side_effect

    data = await coordinator._async_update_data()

    assert len(data[const.DATA_ELECTRICITY].all) == 24
    assert len(data[const.DATA_GAS].all) == 24


async def test_tomorrow_present_merges_today_and_tomorrow(coordinator, api):
    """When tomorrow data is present it should be merged with today's data."""
    today_prices = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    tomorrow_prices = build_market_prices(dt_util.now() + timedelta(days=1), [0.25] * 24, [1.2] * 24)

    async def prices_side_effect(start_date, resolution="PT15M"):
        if start_date == dt_util.now().date():
            return today_prices
        return tomorrow_prices

    api.prices.side_effect = prices_side_effect

    data = await coordinator._async_update_data()

    assert len(data[const.DATA_ELECTRICITY].all) == 48
    assert len(data[const.DATA_GAS].all) == 48


async def test_today_request_exception_without_previous_data_raises_update_failed(coordinator, api):
    """A RequestException fetching today's prices with no cached data raises UpdateFailed."""
    api.prices.side_effect = RequestException("boom")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_today_request_exception_with_previous_data_returns_stale_data(coordinator, api):
    """A RequestException with usable previous data should return the previous data instead of failing."""
    future = dt_util.now() + timedelta(hours=1)
    stale_electricity = build_price_data(future, [0.3] * 5, "electricity")
    stale_gas = build_price_data(future, [1.2] * 5, "gas")
    coordinator.data = {
        const.DATA_ELECTRICITY: stale_electricity,
        const.DATA_GAS: stale_gas,
        const.DATA_MONTH_SUMMARY: None,
        const.DATA_INVOICES: None,
    }

    api.prices.side_effect = RequestException("temporary failure")

    data = await coordinator._async_update_data()

    assert data is coordinator.data
    assert data[const.DATA_ELECTRICITY] is stale_electricity


async def test_today_user_error_raises_config_entry_auth_failed(coordinator, api):
    """A 'user-error:' RequestException should be treated as an auth failure."""
    api.prices.side_effect = RequestException("user-error:some-other-user-error")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_auth_exception_renews_token_and_updates_entry(hass, entry, coordinator, api):
    """AuthException should trigger a token renewal that updates the config entry."""
    api.prices.side_effect = AuthException("token expired")

    renewed = AsyncMock()
    renewed.authToken = "new-access-token"
    renewed.refreshToken = "new-refresh-token"

    async def fake_renew_token():
        # Mirrors the real library: renew_token() updates api._auth in place,
        # which is what the coordinator's persistence helper reads.
        api._auth = renewed
        return renewed

    api.renew_token.side_effect = fake_renew_token

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    api.renew_token.assert_awaited_once()
    assert entry.data[CONF_ACCESS_TOKEN] == "new-access-token"
    assert entry.data[CONF_TOKEN] == "new-refresh-token"
    assert entry.data["site_reference"] == "site-1"
    assert entry.data[CONF_USERNAME] == "someuser"


async def test_auth_exception_renew_failure_raises_config_entry_auth_failed(coordinator, api):
    """If renew_token itself fails with AuthException, a reauth flow should be triggered."""
    api.prices.side_effect = AuthException("token expired")
    api.renew_token.side_effect = AuthException("refresh token expired too")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
