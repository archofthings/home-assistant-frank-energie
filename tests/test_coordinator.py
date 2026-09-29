"""Tests for FrankEnergieCoordinator."""
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie import FrankEnergie
from python_frank_energie.exceptions import (
    AuthException,
    AuthRequiredException,
    FrankEnergieException,
    NetworkError,
    NoMarketPricesAvailableException,
    RequestException,
)
from python_frank_energie.models import Invoices

from custom_components.frank_energie import const
from custom_components.frank_energie.coordinator import FrankEnergieCoordinator
from tests.utils import build_market_prices, build_price_data, make_me, make_month_summary


@pytest.fixture(autouse=True)
def _freeze_midday(freezer):
    """Freeze time at midday UTC, so the UTC date matches the Amsterdam market day.

    The coordinator fetches prices for the Europe/Amsterdam market day, while these tests
    build their data from dt_util.now(). Between 00:00 and 02:00 Amsterdam time the two
    dates differ, which made the tests fail at night. Tests that need another moment
    still call freezer.move_to() themselves.
    """
    freezer.move_to("2026-01-15 12:00:00+00:00")


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
    """An autospec'd mock standing in for a python_frank_energie.FrankEnergie instance.

    Built with create_autospec() so every coroutine method is automatically an
    AsyncMock that enforces the real method's signature, catching tests that
    call/configure it with the wrong arguments.
    """
    mock = create_autospec(FrankEnergie, instance=True)
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


def _install_stale_data(coordinator):
    """Install usable (still-upcoming) stale electricity/gas data on `coordinator`, and return it."""
    future = dt_util.now() + timedelta(hours=1)
    stale_electricity = build_price_data(future, [0.3] * 5, "electricity")
    stale_gas = build_price_data(future, [1.2] * 5, "gas")
    coordinator.data = {
        const.DATA_ELECTRICITY: stale_electricity,
        const.DATA_GAS: stale_gas,
        const.DATA_MONTH_SUMMARY: None,
        const.DATA_INVOICES: None,
    }
    return stale_electricity, stale_gas


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


# --------------------------------------------------------------------------
# 1. NetworkError / AuthRequiredException / plain FrankEnergieException /
#    RequestException / ValueError: everything _async_update_data() routes to
#    _handle_update_error()/_stale_data_or_raise() the same way (except a
#    "user-error:" RequestException, which is covered separately above).
# --------------------------------------------------------------------------

_TODAY_ERRORS = pytest.mark.parametrize(
    "make_exception",
    [
        lambda: NetworkError("network unreachable"),
        lambda: AuthRequiredException("auth required"),
        lambda: FrankEnergieException("something else broke"),
        lambda: RequestException("boom"),
        lambda: ValueError("invalid site_reference"),
    ],
    ids=[
        "network_error",
        "auth_required_exception",
        "plain_frank_energie_exception",
        "request_exception",
        "value_error",
    ],
)


@_TODAY_ERRORS
async def test_today_error_without_previous_data_raises_update_failed(coordinator, api, make_exception):
    """NetworkError/AuthRequiredException/FrankEnergieException/RequestException/ValueError raise UpdateFailed."""
    api.prices.side_effect = make_exception()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@_TODAY_ERRORS
async def test_today_error_with_previous_data_returns_stale_data(coordinator, api, make_exception):
    """The same errors, with usable cached data, return it instead of failing."""
    stale_electricity, stale_gas = _install_stale_data(coordinator)

    api.prices.side_effect = make_exception()

    data = await coordinator._async_update_data()

    assert data is coordinator.data
    assert data[const.DATA_ELECTRICITY] is stale_electricity
    assert data[const.DATA_GAS] is stale_gas


async def test_auth_required_exception_triggers_token_renewal(coordinator, api):
    """AuthRequiredException while fetching today's prices should trigger a token renewal attempt."""
    api.prices.side_effect = AuthRequiredException("token expired")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    api.renew_token.assert_awaited_once()


# --------------------------------------------------------------------------
# 2. Stale data refused when only one segment has upcoming prices
# --------------------------------------------------------------------------

async def test_stale_data_refused_when_only_one_segment_has_upcoming_prices(coordinator, api):
    """Cached data is only reused when BOTH electricity and gas still have upcoming prices."""
    far_past = dt_util.now() - timedelta(hours=6)
    future = dt_util.now() + timedelta(hours=1)
    # 5 hourly entries all ending well before "now" -> none of them are upcoming.
    stale_gas_no_upcoming = build_price_data(far_past, [1.2] * 5, "gas")
    stale_electricity_upcoming = build_price_data(future, [0.3] * 5, "electricity")

    coordinator.data = {
        const.DATA_ELECTRICITY: stale_electricity_upcoming,
        const.DATA_GAS: stale_gas_no_upcoming,
        const.DATA_MONTH_SUMMARY: None,
        const.DATA_INVOICES: None,
    }

    api.prices.side_effect = RequestException("temporary failure")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


# --------------------------------------------------------------------------
# 3. renew_token raising AuthRequiredException -> ConfigEntryAuthFailed
# --------------------------------------------------------------------------

async def test_renew_token_auth_required_exception_raises_config_entry_auth_failed(coordinator, api):
    """If renew_token fails with AuthRequiredException, a reauth flow should be triggered."""
    api.prices.side_effect = AuthException("token expired")
    api.renew_token.side_effect = AuthRequiredException("reauth required")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


# --------------------------------------------------------------------------
# 4. Token persistence
# --------------------------------------------------------------------------

async def test_internally_renewed_tokens_are_persisted_after_successful_update(hass, entry, coordinator, api):
    """Tokens the library renews internally (api._auth) are persisted after a successful update."""
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_ACCESS_TOKEN: "old-access", CONF_TOKEN: "old-refresh"}
    )

    api.is_authenticated = True
    api.user_country.return_value = make_me("NL")
    api.user_prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    api.month_summary.return_value = None
    api.invoices.return_value = None

    renewed = AsyncMock()
    renewed.authToken = "internally-renewed-access"
    renewed.refreshToken = "internally-renewed-refresh"
    api._auth = renewed

    await coordinator._async_update_data()

    assert entry.data[CONF_ACCESS_TOKEN] == "internally-renewed-access"
    assert entry.data[CONF_TOKEN] == "internally-renewed-refresh"
    assert entry.data["site_reference"] == "site-1"
    assert entry.data[CONF_USERNAME] == "someuser"


async def test_matching_internal_tokens_are_not_persisted(hass, entry, coordinator, api, monkeypatch):
    """When api._auth already matches the entry's tokens, the entry should not be updated."""
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_ACCESS_TOKEN: "same-access", CONF_TOKEN: "same-refresh"}
    )

    api.is_authenticated = True
    api.user_country.return_value = make_me("NL")
    api.user_prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    api.month_summary.return_value = None
    api.invoices.return_value = None

    same_auth = AsyncMock()
    same_auth.authToken = "same-access"
    same_auth.refreshToken = "same-refresh"
    api._auth = same_auth

    update_entry_spy = MagicMock(wraps=hass.config_entries.async_update_entry)
    monkeypatch.setattr(hass.config_entries, "async_update_entry", update_entry_spy)

    await coordinator._async_update_data()

    update_entry_spy.assert_not_called()
    assert entry.data[CONF_ACCESS_TOKEN] == "same-access"
    assert entry.data[CONF_TOKEN] == "same-refresh"


async def test_unauthenticated_update_does_not_persist_tokens(hass, entry, coordinator, api):
    """An unauthenticated update must never write tokens into the config entry."""
    api.is_authenticated = False
    api.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    api._auth = AsyncMock(authToken="should-not-be-persisted", refreshToken="also-not-persisted")

    original_data = dict(entry.data)

    await coordinator._async_update_data()

    assert dict(entry.data) == original_data


# --------------------------------------------------------------------------
# 5. Resolution handling
# --------------------------------------------------------------------------

async def test_missing_electricity_fallback_always_uses_pt15m_resolution(coordinator, api):
    """The public fallback is always requested at PT15M, even when gas is PT60M.

    Merges only ever happen within one segment (electricity or gas) across
    days, never between electricity and gas, and gas can be PT60M or even
    daily, which is not a valid resolution to request electricity at.
    """
    api.is_authenticated = True
    api.user_country.return_value = make_me("NL")
    api.user_prices.side_effect = lambda *a, **k: build_market_prices(
        dt_util.now(), [], [1.0] * 24, resolution_minutes=60
    )
    api.prices.side_effect = lambda *a, **k: build_market_prices(
        dt_util.now(), [0.5] * 24, [1.0] * 24, resolution_minutes=60
    )
    api.month_summary.return_value = None
    api.invoices.return_value = None

    await coordinator._async_update_data()

    assert api.prices.await_count > 0
    for call in api.prices.await_args_list:
        assert call.kwargs.get("resolution") == "PT15M"


async def test_merge_mismatched_resolutions_returns_today_only(coordinator):
    """_merge() must not crash when today and tomorrow have different resolutions."""
    today = build_price_data(dt_util.now(), [0.2] * 4, "electricity", resolution_minutes=15)
    tomorrow = build_price_data(dt_util.now() + timedelta(days=1), [0.3] * 2, "electricity", resolution_minutes=60)

    merged = FrankEnergieCoordinator._merge(today, tomorrow)

    assert merged is today


# --------------------------------------------------------------------------
# 6. Missing segments
# --------------------------------------------------------------------------

async def test_user_prices_unavailable_falls_back_to_public_for_both_segments(coordinator, api):
    """NoMarketPricesAvailableException from user_prices() falls back to public prices for both segments."""
    api.is_authenticated = True
    api.user_country.return_value = make_me("NL")
    api.user_prices.side_effect = NoMarketPricesAvailableException("no user prices at all")
    api.prices.side_effect = lambda *a, **k: build_market_prices(dt_util.now(), [0.5] * 24, [1.5] * 24)
    api.month_summary.return_value = None
    api.invoices.return_value = None

    data = await coordinator._async_update_data()

    assert data[const.DATA_ELECTRICITY].all[0].total == pytest.approx(0.5)
    assert data[const.DATA_GAS].all[0].total == pytest.approx(1.5)


async def test_gas_empty_after_fallback_succeeds_with_empty_gas(coordinator, api):
    """Gas can legitimately stay empty (electricity-only customers); the update must still succeed."""
    api.is_authenticated = True
    api.user_country.return_value = make_me("NL")
    api.user_prices.side_effect = lambda *a, **k: build_market_prices(dt_util.now(), [0.5] * 24, [])
    api.prices.side_effect = lambda *a, **k: build_market_prices(dt_util.now(), [0.6] * 24, [])
    api.month_summary.return_value = None
    api.invoices.return_value = None

    data = await coordinator._async_update_data()

    assert len(data[const.DATA_GAS].all) == 0
    assert len(data[const.DATA_ELECTRICITY].all) > 0


async def test_today_electricity_empty_after_fallback_raises_update_failed(coordinator, api):
    """Electricity still empty after falling back to public prices for today is a real failure."""
    api.is_authenticated = True
    api.user_country.return_value = make_me("NL")
    api.user_prices.side_effect = lambda *a, **k: build_market_prices(dt_util.now(), [], [1.0] * 24)
    api.prices.side_effect = lambda *a, **k: build_market_prices(dt_util.now(), [], [1.0] * 24)
    api.month_summary.return_value = None
    api.invoices.return_value = None

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_tomorrow_electricity_empty_after_fallback_succeeds_with_today_only(coordinator, api):
    """Electricity still empty for tomorrow only should not fail the update; today's data is used."""
    api.is_authenticated = True
    api.user_country.return_value = make_me("NL")
    today = dt_util.now().date()

    async def user_prices_side_effect(site_reference, country, start_date):
        if start_date == today:
            return build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
        return build_market_prices(dt_util.now() + timedelta(days=1), [], [1.0] * 24)

    api.user_prices.side_effect = user_prices_side_effect
    # Public fallback also has no electricity, for either date.
    api.prices.side_effect = lambda *a, **k: build_market_prices(dt_util.now(), [], [1.0] * 24)
    api.month_summary.return_value = None
    api.invoices.return_value = None

    data = await coordinator._async_update_data()

    assert len(data[const.DATA_ELECTRICITY].all) == 24


# --------------------------------------------------------------------------
# 7. Country handling
# --------------------------------------------------------------------------

async def test_be_country_empty_user_prices_uses_country_prices_not_prices(coordinator, api):
    """A BE user with empty user prices should fall back to country_prices(), not the NL-only prices()."""
    api.is_authenticated = True
    api.user_country.return_value = make_me("BE")
    api.user_prices.side_effect = lambda *a, **k: build_market_prices(dt_util.now(), [], [])
    api.country_prices.side_effect = lambda *a, **k: build_market_prices(dt_util.now(), [0.4] * 24, [1.4] * 24)
    api.month_summary.return_value = None
    api.invoices.return_value = None

    await coordinator._async_update_data()

    assert api.country_prices.await_count > 0
    assert api.prices.await_count == 0
    for call in api.country_prices.await_args_list:
        assert call.args[0] == "BE"


# --------------------------------------------------------------------------
# 8. Market day timezone
# --------------------------------------------------------------------------

async def test_market_day_uses_amsterdam_timezone_not_ha_timezone(hass, coordinator, api, freezer):
    """"Today" must be computed in Europe/Amsterdam even when the HA instance uses a different timezone."""
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-03-10 23:30:00+00:00")

    api.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)

    await coordinator._async_update_data()

    # Amsterdam (UTC+1 in March, before the DST switch on 2026-03-29) is
    # already on 2026-03-11 at this UTC instant, even though UTC (the HA
    # instance's own timezone here) is still on 2026-03-10.
    assert api.prices.await_args_list[0].args[0] == date(2026, 3, 11)


# --------------------------------------------------------------------------
# 9. Token renewal hardening / persistence on failure (see commit 3a57d03,
# "Harden token renewal and persist tokens on failed updates").
# --------------------------------------------------------------------------

async def test_renew_token_network_error_with_previous_data_returns_stale_data(coordinator, api):
    """A NetworkError raised by renew_token() (during an AuthException) must not crash; stale data is served.

    _try_renew_token() must catch the non-auth FrankEnergieException (here
    NetworkError) from renew_token() and return normally so the caller falls
    through to _stale_data_or_raise() instead of the exception propagating
    uncaught.
    """
    api.prices.side_effect = AuthException("token expired")
    api.renew_token.side_effect = NetworkError("renewal network unreachable")

    stale_electricity, stale_gas = _install_stale_data(coordinator)

    data = await coordinator._async_update_data()

    assert data is coordinator.data
    assert data[const.DATA_ELECTRICITY] is stale_electricity


async def test_renew_token_network_error_without_previous_data_raises_update_failed(coordinator, api):
    """A NetworkError from renew_token() with no cached data must raise UpdateFailed, not propagate raw."""
    api.prices.side_effect = AuthException("token expired")
    api.renew_token.side_effect = NetworkError("renewal network unreachable")

    with pytest.raises(UpdateFailed) as excinfo:
        await coordinator._async_update_data()

    # Must surface as the controlled UpdateFailed retry signal, not the raw
    # NetworkError from renew_token() propagating out uncaught.
    assert excinfo.type is UpdateFailed


async def test_internally_renewed_tokens_persisted_when_today_fetch_fails(hass, entry, coordinator, api):
    """Tokens renewed internally (api._auth) must be persisted even when the update itself fails.

    The finally block in _async_update_data() persists tokens the library may
    have renewed transparently inside _query() during any of the awaited
    calls, including ones that ultimately raised, so a renewed token is never
    lost when the update fails later in the same cycle.
    """
    api.is_authenticated = True
    api.user_country.return_value = make_me("NL")
    api.user_prices.side_effect = NetworkError("network unreachable")

    renewed = AsyncMock()
    renewed.authToken = "internally-renewed-access"
    renewed.refreshToken = "internally-renewed-refresh"
    api._auth = renewed

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert entry.data[CONF_ACCESS_TOKEN] == "internally-renewed-access"
    assert entry.data[CONF_TOKEN] == "internally-renewed-refresh"
    assert entry.data["site_reference"] == "site-1"
    assert entry.data[CONF_USERNAME] == "someuser"


# --------------------------------------------------------------------------
# 10. Retry the update once after a successful token renewal (see commit
# 088606a, "Retry the update once after a successful token renewal").
# --------------------------------------------------------------------------

def _fake_renew_token(api, new_access_token="new-access-token", new_refresh_token="new-refresh-token"):
    """Build a renew_token() side effect mirroring the real library's api._auth mutation."""
    renewed = AsyncMock()
    renewed.authToken = new_access_token
    renewed.refreshToken = new_refresh_token

    async def fake_renew_token():
        api._auth = renewed
        return renewed

    return fake_renew_token


async def test_auth_exception_retry_succeeds_returns_fresh_data(coordinator, api):
    """AuthException on the first fetch, successful renewal, then a successful retry returns fresh data."""
    today = dt_util.now().date()
    tomorrow = today + timedelta(days=1)
    today_prices = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    tomorrow_prices = build_market_prices(dt_util.now() + timedelta(days=1), [0.3] * 24, [1.1] * 24)

    today_call_count = 0

    async def prices_side_effect(start_date, resolution="PT15M"):
        nonlocal today_call_count
        if start_date == today:
            today_call_count += 1
            if today_call_count == 1:
                raise AuthException("token expired")
            return today_prices
        if start_date == tomorrow:
            return tomorrow_prices
        raise AssertionError(f"Unexpected date {start_date}")

    api.prices.side_effect = prices_side_effect
    api.renew_token.side_effect = _fake_renew_token(api)

    data = await coordinator._async_update_data()

    assert data is not None
    assert len(data[const.DATA_ELECTRICITY].all) == 48
    assert data[const.DATA_ELECTRICITY].all[0].total == pytest.approx(0.2)
    api.renew_token.assert_awaited_once()
    assert today_call_count == 2


async def test_auth_exception_retry_fails_again_no_second_renewal_with_stale_data(coordinator, api):
    """An AuthException on the retry itself must not trigger a second renewal; stale data is served instead."""
    stale_electricity, stale_gas = _install_stale_data(coordinator)

    # Every prices() call raises, including the retry's.
    api.prices.side_effect = AuthException("token expired")
    api.renew_token.side_effect = _fake_renew_token(api)

    data = await coordinator._async_update_data()

    assert data is coordinator.data
    assert data[const.DATA_ELECTRICITY] is stale_electricity
    api.renew_token.assert_awaited_once()


async def test_auth_exception_retry_fails_again_no_second_renewal_without_stale_data(coordinator, api):
    """Same as above, but with no cached data: UpdateFailed is raised and renewal still only happens once."""
    api.prices.side_effect = AuthException("token expired")
    api.renew_token.side_effect = _fake_renew_token(api)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    api.renew_token.assert_awaited_once()


async def test_retry_user_error_raises_config_entry_auth_failed(coordinator, api):
    """A 'user-error:' RequestException on the retry must be treated as an auth failure, not another renewal."""
    today = dt_util.now().date()
    today_call_count = 0

    async def prices_side_effect(start_date, resolution="PT15M"):
        nonlocal today_call_count
        if start_date == today:
            today_call_count += 1
            if today_call_count == 1:
                raise AuthException("token expired")
            raise RequestException("user-error:different-account")
        return build_market_prices(dt_util.now() + timedelta(days=1), [0.3] * 24, [1.1] * 24)

    api.prices.side_effect = prices_side_effect
    api.renew_token.side_effect = _fake_renew_token(api)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    api.renew_token.assert_awaited_once()


async def test_retry_network_error_with_stale_data_returns_stale_data(coordinator, api):
    """A NetworkError on the retry must fall back to stale data, like the first attempt would."""
    today = dt_util.now().date()
    today_call_count = 0

    async def prices_side_effect(start_date, resolution="PT15M"):
        nonlocal today_call_count
        if start_date == today:
            today_call_count += 1
            if today_call_count == 1:
                raise AuthException("token expired")
            raise NetworkError("retry network unreachable")
        return build_market_prices(dt_util.now() + timedelta(days=1), [0.3] * 24, [1.1] * 24)

    api.prices.side_effect = prices_side_effect
    api.renew_token.side_effect = _fake_renew_token(api)

    stale_electricity, stale_gas = _install_stale_data(coordinator)

    data = await coordinator._async_update_data()

    assert data is coordinator.data
    assert data[const.DATA_ELECTRICITY] is stale_electricity
    api.renew_token.assert_awaited_once()


async def test_retry_network_error_without_stale_data_raises_update_failed(coordinator, api):
    """A NetworkError on the retry with no cached data must raise UpdateFailed."""
    today = dt_util.now().date()
    today_call_count = 0

    async def prices_side_effect(start_date, resolution="PT15M"):
        nonlocal today_call_count
        if start_date == today:
            today_call_count += 1
            if today_call_count == 1:
                raise AuthException("token expired")
            raise NetworkError("retry network unreachable")
        return build_market_prices(dt_util.now() + timedelta(days=1), [0.3] * 24, [1.1] * 24)

    api.prices.side_effect = prices_side_effect
    api.renew_token.side_effect = _fake_renew_token(api)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    api.renew_token.assert_awaited_once()


async def test_renew_token_network_error_does_not_retry_fetch(coordinator, api):
    """If renew_token() itself fails with a non-auth error, _fetch_all() must not be retried."""
    api.prices.side_effect = AuthException("token expired")
    api.renew_token.side_effect = NetworkError("renewal network unreachable")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    # Only the first attempt's call to today's prices, never a retry.
    assert api.prices.await_count == 1
    api.renew_token.assert_awaited_once()


async def test_auth_exception_from_month_summary_retry_succeeds_returns_fresh_data(coordinator, api):
    """An AuthException from month_summary() (prices already succeeded) triggers a renewal, then a retry.

    _fetch_all() fetches prices before month_summary/invoices, so an
    AuthException raised by month_summary() still propagates out of
    _fetch_all() as a whole and is handled the same way as one from prices():
    a token renewal followed by one full retry of _fetch_all(), including
    prices again.
    """
    today = dt_util.now().date()

    async def user_prices_side_effect(site_reference, country, start_date):
        if start_date == today:
            return build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
        return build_market_prices(dt_util.now() + timedelta(days=1), [0.3] * 24, [1.1] * 24)

    api.is_authenticated = True
    api.user_country.return_value = make_me("NL")
    api.user_prices.side_effect = user_prices_side_effect
    api.invoices.return_value = Invoices.empty()

    month_summary_call_count = 0
    fresh_summary = make_month_summary()

    async def month_summary_side_effect(site_reference):
        nonlocal month_summary_call_count
        month_summary_call_count += 1
        if month_summary_call_count == 1:
            raise AuthException("token expired")
        return fresh_summary

    api.month_summary.side_effect = month_summary_side_effect
    api.renew_token.side_effect = _fake_renew_token(api)

    data = await coordinator._async_update_data()

    assert data is not None
    assert data[const.DATA_MONTH_SUMMARY] is fresh_summary
    assert len(data[const.DATA_ELECTRICITY].all) == 48
    api.renew_token.assert_awaited_once()
    assert month_summary_call_count == 2
    # user_prices is called twice (today + tomorrow) per full attempt.
    assert api.user_prices.await_count == 4


async def test_auth_exception_from_invoices_retry_succeeds_returns_fresh_data(coordinator, api):
    """An AuthException from invoices() (prices and month_summary already succeeded) triggers a renewal + retry."""
    today = dt_util.now().date()

    async def user_prices_side_effect(site_reference, country, start_date):
        if start_date == today:
            return build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
        return build_market_prices(dt_util.now() + timedelta(days=1), [0.3] * 24, [1.1] * 24)

    api.is_authenticated = True
    api.user_country.return_value = make_me("NL")
    api.user_prices.side_effect = user_prices_side_effect
    api.month_summary.return_value = make_month_summary()

    invoices_call_count = 0
    fresh_invoices = Invoices.empty()

    async def invoices_side_effect(site_reference):
        nonlocal invoices_call_count
        invoices_call_count += 1
        if invoices_call_count == 1:
            raise AuthException("token expired")
        return fresh_invoices

    api.invoices.side_effect = invoices_side_effect
    api.renew_token.side_effect = _fake_renew_token(api)

    data = await coordinator._async_update_data()

    assert data is not None
    assert data[const.DATA_INVOICES] is fresh_invoices
    assert len(data[const.DATA_ELECTRICITY].all) == 48
    api.renew_token.assert_awaited_once()
    assert invoices_call_count == 2
    assert api.user_prices.await_count == 4


async def test_renewed_tokens_end_up_in_entry_data_after_successful_retry(hass, entry, coordinator, api):
    """Tokens renewed via renew_token() ahead of a successful retry are persisted, keeping site_reference."""
    today = dt_util.now().date()
    today_call_count = 0

    async def prices_side_effect(start_date, resolution="PT15M"):
        nonlocal today_call_count
        if start_date == today:
            today_call_count += 1
            if today_call_count == 1:
                raise AuthException("token expired")
            return build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
        return build_market_prices(dt_util.now() + timedelta(days=1), [0.3] * 24, [1.1] * 24)

    api.prices.side_effect = prices_side_effect
    api.renew_token.side_effect = _fake_renew_token(api, "retry-access-token", "retry-refresh-token")

    await coordinator._async_update_data()

    assert entry.data[CONF_ACCESS_TOKEN] == "retry-access-token"
    assert entry.data[CONF_TOKEN] == "retry-refresh-token"
    assert entry.data["site_reference"] == "site-1"
