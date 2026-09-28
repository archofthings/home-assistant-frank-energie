"""Tests for the Frank Energie config flow."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_AUTHENTICATION, CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.exceptions import AuthException, NetworkError
from python_frank_energie.models import DeliverySite, Invoices, MonthSummary

from custom_components.frank_energie import const
from custom_components.frank_energie.config_flow import SITE_REFERENCE, _merge_reauth_data, _same_account
from tests.utils import build_market_prices, make_delivery_site, make_user_sites


def _configure_authenticated_api(mock_api):
    """Set up mock_api with enough authenticated responses for a full setup (see tests/test_init.py)."""
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


@pytest.fixture
def mock_config_flow_api(monkeypatch):
    """Patch the FrankEnergie class used by config_flow with an async-context-manager mock.

    config_flow uses ``async with FrankEnergie() as api:`` (the real client's
    __aenter__ returns self, __aexit__ closes the session), so the mock
    instance must support that protocol.
    """
    api = MagicMock(name="FrankEnergieConfigFlowApi")
    api.__aenter__ = AsyncMock(return_value=api)
    api.__aexit__ = AsyncMock(return_value=False)
    api.login = AsyncMock()
    monkeypatch.setattr(
        "custom_components.frank_energie.config_flow.FrankEnergie",
        MagicMock(return_value=api),
    )
    return api


async def test_reauth_without_username_shows_login_form(hass, enable_custom_integrations):
    """A reauth flow on an entry without a username in its data must not raise KeyError.

    Some entries (e.g. those created via the "public prices only" flow, or
    older entries predating CONF_USERNAME) have no CONF_USERNAME in their
    data. Starting a reauth flow for such an entry must still show the login
    form (pre-filled with no default username) instead of crashing.
    """
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )

    assert result["type"] == "form"
    assert result["step_id"] == "login"


# --------------------------------------------------------------------------
# Regression: entry data kept on reauth, connection errors reported (see
# commit f42a733, "Keep entry data on reauth and report connection errors in
# config flow").
# --------------------------------------------------------------------------

async def test_reauth_login_keeps_existing_entry_data(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """A successful reauth login must merge new tokens into the entry, keeping e.g. site_reference."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1", CONF_USERNAME: "olduser"},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    # The reauth flow reloads the entry on success; configure the (separately
    # mocked) FrankEnergie client used by __init__.py so that reload succeeds
    # without hitting the real API.
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "login"

    auth = MagicMock(authToken="new-access-token", refreshToken="new-refresh-token")
    mock_config_flow_api.login.return_value = auth

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "olduser", CONF_PASSWORD: "secret"},
    )
    await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "reauth_successful"

    assert entry.data["site_reference"] == "site-1"
    assert entry.data[CONF_USERNAME] == "olduser"
    assert entry.data[CONF_ACCESS_TOKEN] == "new-access-token"
    assert entry.data[CONF_TOKEN] == "new-refresh-token"


async def test_login_network_error_shows_cannot_connect(hass, enable_custom_integrations, mock_config_flow_api):
    """A non-auth FrankEnergieException (e.g. NetworkError) from login() must show 'cannot_connect', not crash."""
    result = await hass.config_entries.flow.async_init(
        const.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_AUTHENTICATION: True})
    assert result["step_id"] == "login"

    mock_config_flow_api.login.side_effect = NetworkError("network unreachable")

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "someuser", CONF_PASSWORD: "secret"}
    )

    assert result2["type"] == "form"
    assert result2["step_id"] == "login"
    assert result2["errors"] == {"base": "cannot_connect"}


# --------------------------------------------------------------------------
# Reauthenticating with a different account is rejected outright (standard HA
# pattern): the entry must be left completely untouched, and the user is
# pointed at adding the other account as a new integration instead. An
# earlier approach accepted the account change and only dropped
# site_reference; that caused duplicate entries and stale unique IDs.
# --------------------------------------------------------------------------

async def test_reauth_same_account_different_case_and_whitespace_keeps_site_reference(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """Reauth with the same username (different case/whitespace) must keep site_reference."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1", CONF_USERNAME: "  User@Example.com "},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    # site_reference stays set, so the reload after reauth skips site
    # discovery entirely and just re-fetches public prices.
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "login"

    auth = MagicMock(authToken="new-access-token", refreshToken="new-refresh-token")
    mock_config_flow_api.login.return_value = auth

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
    )
    await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "reauth_successful"

    assert entry.data["site_reference"] == "site-1"
    assert entry.data[CONF_USERNAME] == "user@example.com"
    assert entry.data[CONF_ACCESS_TOKEN] == "new-access-token"
    assert entry.data[CONF_TOKEN] == "new-refresh-token"
    assert entry.unique_id == "frank_energie"
    mock_frank_energie_class.UserSites.assert_not_awaited()


async def test_reauth_different_account_is_rejected(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """Reauth with a different username must be rejected, leaving the entry completely untouched."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-1",
            CONF_USERNAME: "olduser@example.com",
            CONF_ACCESS_TOKEN: "old-access-token",
            CONF_TOKEN: "old-refresh-token",
        },
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "login"

    auth = MagicMock(authToken="new-access-token", refreshToken="new-refresh-token")
    mock_config_flow_api.login.return_value = auth

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "newuser@example.com", CONF_PASSWORD: "secret"},
    )
    await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "wrong_account"

    assert entry.data["site_reference"] == "site-1"
    assert entry.data[CONF_USERNAME] == "olduser@example.com"
    assert entry.data[CONF_ACCESS_TOKEN] == "old-access-token"
    assert entry.data[CONF_TOKEN] == "old-refresh-token"
    assert entry.unique_id == "frank_energie"
    assert entry.state is ConfigEntryState.NOT_LOADED
    mock_frank_energie_class.UserSites.assert_not_awaited()


async def test_reauth_different_account_with_existing_entry_for_that_account_is_rejected(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """Reauth with a different account that already has its own entry must still abort, leaving both untouched.

    Guards against silently merging into (or duplicating) the other
    account's existing entry: there must still be exactly one entry per
    account afterwards.
    """
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-1",
            CONF_USERNAME: "olduser@example.com",
            CONF_ACCESS_TOKEN: "old-access-token",
            CONF_TOKEN: "old-refresh-token",
        },
        unique_id="olduser@example.com",
    )
    entry.add_to_hass(hass)

    other_entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-2",
            CONF_USERNAME: "newuser@example.com",
            CONF_ACCESS_TOKEN: "other-access-token",
            CONF_TOKEN: "other-refresh-token",
        },
        unique_id="newuser@example.com",
    )
    other_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "login"

    auth = MagicMock(authToken="new-access-token", refreshToken="new-refresh-token")
    mock_config_flow_api.login.return_value = auth

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "newuser@example.com", CONF_PASSWORD: "secret"},
    )
    await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "wrong_account"

    # The entry being reauthenticated is left completely untouched.
    assert entry.data["site_reference"] == "site-1"
    assert entry.data[CONF_USERNAME] == "olduser@example.com"
    assert entry.data[CONF_ACCESS_TOKEN] == "old-access-token"
    assert entry.data[CONF_TOKEN] == "old-refresh-token"
    assert entry.state is ConfigEntryState.NOT_LOADED

    # So is the other account's own, pre-existing entry.
    assert other_entry.data["site_reference"] == "site-2"
    assert other_entry.data[CONF_USERNAME] == "newuser@example.com"
    assert other_entry.data[CONF_ACCESS_TOKEN] == "other-access-token"
    assert other_entry.data[CONF_TOKEN] == "other-refresh-token"

    # Still exactly one entry per account: no duplicate was created.
    entries = hass.config_entries.async_entries(const.DOMAIN)
    assert len(entries) == 2
    assert {e.unique_id for e in entries} == {"olduser@example.com", "newuser@example.com"}
    mock_frank_energie_class.UserSites.assert_not_awaited()


async def test_reauth_legacy_entry_without_stored_username_drops_site_reference(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """Reauth on a legacy entry with no stored username must drop site_reference (no account to compare against)."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    mock_frank_energie_class.UserSites.return_value = make_user_sites([])

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "login"

    auth = MagicMock(authToken="new-access-token", refreshToken="new-refresh-token")
    mock_config_flow_api.login.return_value = auth

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "someuser@example.com", CONF_PASSWORD: "secret"},
    )
    await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "reauth_successful"

    assert "site_reference" not in entry.data
    assert entry.data[CONF_USERNAME] == "someuser@example.com"
    assert entry.unique_id == "frank_energie"


async def test_reauth_legacy_entry_rediscovers_site_and_loads(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """A legacy entry's reauth, followed by successful site rediscovery, ends up LOADED.

    site_reference is dropped on login (no stored username to compare
    against), so the reload that follows rediscovers it via UserSites() and
    rebuilds the title from the new site's address.
    """
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    site = make_delivery_site("new-site", "IN_DELIVERY", street="Vondelstraat", house_number="7")
    mock_frank_energie_class.UserSites.return_value = make_user_sites([site])
    _configure_authenticated_api(mock_frank_energie_class)

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "login"

    auth = MagicMock(authToken="new-access-token", refreshToken="new-refresh-token")
    mock_config_flow_api.login.return_value = auth

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "someuser@example.com", CONF_PASSWORD: "secret"},
    )
    await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "reauth_successful"

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data["site_reference"] == "new-site"
    assert entry.title == "Vondelstraat 7"
    assert entry.data[CONF_USERNAME] == "someuser@example.com"
    assert entry.data[CONF_ACCESS_TOKEN] == "new-access-token"
    assert entry.data[CONF_TOKEN] == "new-refresh-token"


async def test_reauth_same_account_reloads_entry_to_loaded(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """A successful same-account reauth reloads the entry, ending up LOADED with the new tokens."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1", CONF_USERNAME: "user@example.com"},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    # site_reference stays set, so the reload after reauth skips site
    # discovery entirely and just re-fetches public prices.
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "login"

    auth = MagicMock(authToken="new-access-token", refreshToken="new-refresh-token")
    mock_config_flow_api.login.return_value = auth

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
    )
    await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "reauth_successful"

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_ACCESS_TOKEN] == "new-access-token"
    assert entry.data[CONF_TOKEN] == "new-refresh-token"


async def test_wrong_account_abort_reason_translated_in_all_locale_files():
    """"wrong_account" must have real translated text in strings.json, en.json and nl.json.

    Without an entry under config.abort in every locale file, Home Assistant
    falls back to showing the raw abort reason key ("wrong_account") in the
    UI instead of a human-readable message.
    """
    integration_dir = Path(__file__).resolve().parent.parent / "custom_components" / "frank_energie"
    locale_files = [
        integration_dir / "strings.json",
        integration_dir / "translations" / "en.json",
        integration_dir / "translations" / "nl.json",
    ]

    for locale_file in locale_files:
        data = json.loads(locale_file.read_text(encoding="utf-8"))
        message = data["config"]["abort"]["wrong_account"]

        assert isinstance(message, str)
        assert message.strip() != ""
        assert message != "wrong_account", f"{locale_file} shows the raw abort reason key, not translated text"


# --------------------------------------------------------------------------
# Unit tests for _same_account() and _merge_reauth_data().
# --------------------------------------------------------------------------

def test_same_account_case_and_whitespace_insensitive():
    """Usernames differing only by case/surrounding whitespace are treated as the same account."""
    assert _same_account("  User@Example.com ", "user@example.com") is True


def test_same_account_different_usernames():
    """Different usernames are not the same account."""
    assert _same_account("olduser", "newuser") is False


def test_same_account_no_stored_username():
    """No stored username (legacy entry) has no account to compare against."""
    assert _same_account(None, "newuser") is False


def test_merge_reauth_data_keeps_site_reference_when_not_dropped():
    """With drop_site_reference=False the existing entry data, including site_reference, is kept."""
    entry_data = {"site_reference": "site-1", CONF_USERNAME: "  User@Example.com "}
    new_data = {CONF_USERNAME: "user@example.com", CONF_ACCESS_TOKEN: "new-token", CONF_TOKEN: "new-refresh"}

    result = _merge_reauth_data(entry_data, new_data, drop_site_reference=False)

    assert result["site_reference"] == "site-1"
    assert result[CONF_USERNAME] == "user@example.com"
    assert result[CONF_ACCESS_TOKEN] == "new-token"
    assert result[CONF_TOKEN] == "new-refresh"


def test_merge_reauth_data_drops_site_reference_when_requested():
    """With drop_site_reference=True the old site_reference is dropped, e.g. for a legacy entry."""
    entry_data = {"site_reference": "site-1"}
    new_data = {CONF_USERNAME: "newuser", CONF_ACCESS_TOKEN: "new-token", CONF_TOKEN: "new-refresh"}

    result = _merge_reauth_data(entry_data, new_data, drop_site_reference=True)

    assert "site_reference" not in result
    assert result[CONF_USERNAME] == "newuser"


def test_merge_reauth_data_no_site_reference_does_not_raise():
    """An entry without site_reference must not raise KeyError when dropping is requested."""
    entry_data = {CONF_USERNAME: "olduser"}
    new_data = {CONF_USERNAME: "newuser", CONF_ACCESS_TOKEN: "new-token", CONF_TOKEN: "new-refresh"}

    result = _merge_reauth_data(entry_data, new_data, drop_site_reference=True)

    assert "site_reference" not in result
    assert result[CONF_USERNAME] == "newuser"


# --------------------------------------------------------------------------
# Site selection at login (see commit 366cea2, "Let users choose their
# delivery site and change it via reconfigure").
# --------------------------------------------------------------------------


async def _start_login_flow(hass):
    """Start a SOURCE_USER flow and advance it to the login step."""
    result = await hass.config_entries.flow.async_init(
        const.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_AUTHENTICATION: True})
    assert result["step_id"] == "login"
    return result


async def test_login_single_site_creates_entry_with_site_reference_and_address_title(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """A login that discovers exactly one IN_DELIVERY site creates the entry directly, titled by its address."""
    site = make_delivery_site("site-1", "IN_DELIVERY", street="Vondelstraat", house_number="7")
    mock_config_flow_api.UserSites = AsyncMock(return_value=make_user_sites([site]))
    mock_config_flow_api.login.return_value = MagicMock(authToken="access-token", refreshToken="refresh-token")
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)

    result = await _start_login_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
    )
    await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert result2["title"] == "Vondelstraat 7"
    assert result2["data"]["site_reference"] == "site-1"
    assert result2["data"][CONF_USERNAME] == "user@example.com"
    assert result2["data"][CONF_ACCESS_TOKEN] == "access-token"


async def test_login_single_site_without_address_falls_back_to_username_title(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """When the single discovered site has no address, the entry title falls back to the username."""
    site = DeliverySite(
        addressHasMultipleSites=False,
        propositionType=None,
        reference="site-1",
        segments=["ELECTRICITY", "GAS"],
        address=None,
        status="IN_DELIVERY",
        deliveryStartDate=None,
        deliveryEndDate=None,
        firstMeterReadingDate=None,
        lastMeterReadingDate=None,
    )
    mock_config_flow_api.UserSites = AsyncMock(return_value=make_user_sites([site]))
    mock_config_flow_api.login.return_value = MagicMock(authToken="access-token", refreshToken="refresh-token")
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)

    result = await _start_login_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
    )
    await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert result2["title"] == "user@example.com"
    assert result2["data"]["site_reference"] == "site-1"


async def test_login_multiple_sites_shows_site_step_and_creates_entry_with_chosen_site(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """With more than one IN_DELIVERY site, the user is shown a "site" form and can choose one."""
    site1 = make_delivery_site("site-1", "IN_DELIVERY", street="Vondelstraat", house_number="7")
    site2 = make_delivery_site("site-2", "IN_DELIVERY", street="Kalverstraat", house_number="99")
    mock_config_flow_api.UserSites = AsyncMock(return_value=make_user_sites([site1, site2]))
    mock_config_flow_api.login.return_value = MagicMock(authToken="access-token", refreshToken="refresh-token")
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)

    result = await _start_login_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
    )

    assert result2["type"] == "form"
    assert result2["step_id"] == "site"

    options = result2["data_schema"].schema[
        next(k for k in result2["data_schema"].schema if getattr(k, "schema", None) == SITE_REFERENCE)
    ].config["options"]
    assert {opt["value"] for opt in options} == {"site-1", "site-2"}
    assert {opt["label"] for opt in options} == {"Vondelstraat 7", "Kalverstraat 99"}

    result3 = await hass.config_entries.flow.async_configure(result2["flow_id"], {SITE_REFERENCE: "site-2"})
    await hass.async_block_till_done()

    assert result3["type"] == "create_entry"
    assert result3["title"] == "Kalverstraat 99"
    assert result3["data"]["site_reference"] == "site-2"
    assert result3["data"][CONF_USERNAME] == "user@example.com"


async def test_login_no_sites_aborts(hass, enable_custom_integrations, mock_config_flow_api):
    """When the account has no IN_DELIVERY sites at all, the flow aborts with no_sites."""
    mock_config_flow_api.UserSites = AsyncMock(return_value=make_user_sites([]))
    mock_config_flow_api.login.return_value = MagicMock(authToken="access-token", refreshToken="refresh-token")

    result = await _start_login_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
    )

    assert result2["type"] == "abort"
    assert result2["reason"] == "no_sites"


async def test_login_usersites_auth_exception_shows_invalid_auth(
    hass, enable_custom_integrations, mock_config_flow_api
):
    """An AuthException from UserSites() (after a successful login) shows the login form with invalid_auth."""
    mock_config_flow_api.UserSites = AsyncMock(side_effect=AuthException("token rejected"))
    mock_config_flow_api.login.return_value = MagicMock(authToken="access-token", refreshToken="refresh-token")

    result = await _start_login_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
    )

    assert result2["type"] == "form"
    assert result2["step_id"] == "login"
    assert result2["errors"] == {"base": "invalid_auth"}


async def test_login_usersites_network_error_shows_cannot_connect(
    hass, enable_custom_integrations, mock_config_flow_api
):
    """A NetworkError from UserSites() (after a successful login) shows the login form with cannot_connect."""
    mock_config_flow_api.UserSites = AsyncMock(side_effect=NetworkError("unreachable"))
    mock_config_flow_api.login.return_value = MagicMock(authToken="access-token", refreshToken="refresh-token")

    result = await _start_login_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
    )

    assert result2["type"] == "form"
    assert result2["step_id"] == "login"
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_login_duplicate_username_aborts_already_configured(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """Logging in with a username that already has a config entry aborts as already_configured."""
    existing = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1", CONF_USERNAME: "user@example.com"},
        unique_id="user@example.com",
    )
    existing.add_to_hass(hass)

    site = make_delivery_site("site-1", "IN_DELIVERY")
    mock_config_flow_api.UserSites = AsyncMock(return_value=make_user_sites([site]))
    mock_config_flow_api.login.return_value = MagicMock(authToken="access-token", refreshToken="refresh-token")

    result = await _start_login_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
    )

    assert result2["type"] == "abort"
    assert result2["reason"] == "already_configured"


# --------------------------------------------------------------------------
# Reconfigure flow (see commit 366cea2).
# --------------------------------------------------------------------------


async def test_reconfigure_without_token_aborts_not_supported(hass, enable_custom_integrations):
    """An entry with no stored access token cannot be reconfigured (no account to fetch sites for)."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_not_supported"


async def test_reconfigure_shows_form_defaulting_to_current_site_and_submits_new_site(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """The reconfigure form defaults to the current site; submitting another site updates and reloads the entry."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-1",
            CONF_USERNAME: "user@example.com",
            CONF_ACCESS_TOKEN: "old-access-token",
            CONF_TOKEN: "old-refresh-token",
            "extra_field": "keep-me",
        },
        unique_id="frank_energie",
        title="Oldstraat 1",
    )
    entry.add_to_hass(hass)

    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    site1 = make_delivery_site("site-1", "IN_DELIVERY", street="Oldstraat", house_number="1")
    site2 = make_delivery_site("site-2", "IN_DELIVERY", street="Newstraat", house_number="99")
    mock_config_flow_api.UserSites = AsyncMock(return_value=make_user_sites([site1, site2]))
    # Simulate the library silently renewing tokens inside UserSites().
    mock_config_flow_api._auth = MagicMock(authToken="renewed-access-token", refreshToken="renewed-refresh-token")

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"

    schema = result["data_schema"].schema
    site_key = next(k for k in schema if getattr(k, "schema", None) == SITE_REFERENCE)
    assert site_key.default() == "site-1"

    result2 = await hass.config_entries.flow.async_configure(result["flow_id"], {SITE_REFERENCE: "site-2"})
    await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "reconfigure_successful"

    assert entry.data["site_reference"] == "site-2"
    assert entry.title == "Newstraat 99"
    assert entry.data["extra_field"] == "keep-me"
    assert entry.data[CONF_USERNAME] == "user@example.com"
    assert entry.data[CONF_ACCESS_TOKEN] == "renewed-access-token"
    assert entry.data[CONF_TOKEN] == "renewed-refresh-token"
    assert entry.state is ConfigEntryState.LOADED


async def test_reconfigure_first_fetch_failing_aborts_cannot_connect(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """A fetch failure on the very first reconfigure step (showing the form) aborts with cannot_connect."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-1",
            CONF_USERNAME: "user@example.com",
            CONF_ACCESS_TOKEN: "old-access-token",
            CONF_TOKEN: "old-refresh-token",
        },
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    mock_config_flow_api.UserSites = AsyncMock(side_effect=NetworkError("unreachable"))

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )

    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"


async def test_reconfigure_fetch_failing_on_submit_shows_form_with_error(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """A fetch failure on submit (after the form was already shown successfully) re-shows the form with an error."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-1",
            CONF_USERNAME: "user@example.com",
            CONF_ACCESS_TOKEN: "old-access-token",
            CONF_TOKEN: "old-refresh-token",
        },
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    site1 = make_delivery_site("site-1", "IN_DELIVERY")
    mock_config_flow_api.UserSites = AsyncMock(return_value=make_user_sites([site1]))

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["type"] == "form"

    mock_config_flow_api.UserSites = AsyncMock(side_effect=NetworkError("unreachable"))

    result2 = await hass.config_entries.flow.async_configure(result["flow_id"], {SITE_REFERENCE: "site-1"})

    assert result2["type"] == "form"
    assert result2["step_id"] == "reconfigure"
    assert result2["errors"] == {"base": "cannot_connect"}

    # The entry must be untouched: the failed submit did not update or reload it.
    assert entry.data["site_reference"] == "site-1"
    assert entry.data[CONF_ACCESS_TOKEN] == "old-access-token"


async def test_reconfigure_no_sites_aborts_no_sites(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """When the account has no IN_DELIVERY sites, reconfigure aborts with no_sites."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-1",
            CONF_USERNAME: "user@example.com",
            CONF_ACCESS_TOKEN: "old-access-token",
            CONF_TOKEN: "old-refresh-token",
        },
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    mock_config_flow_api.UserSites = AsyncMock(return_value=make_user_sites([]))

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )

    assert result["type"] == "abort"
    assert result["reason"] == "no_sites"


# --------------------------------------------------------------------------
# Regression: the unauthenticated ("public prices only") flow is unchanged.
# --------------------------------------------------------------------------


async def test_unauthenticated_flow_creates_entry_with_no_data(hass, enable_custom_integrations):
    """Declining to sign in still creates an entry with empty data, unaffected by site selection."""
    result = await hass.config_entries.flow.async_init(
        const.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_AUTHENTICATION: False})

    assert result2["type"] == "create_entry"
    assert result2["data"] == {}


# --------------------------------------------------------------------------
# prices_timezone option (see commit d6a5dc3, "Add option for the time zone
# of price times").
# --------------------------------------------------------------------------


async def test_unauthenticated_flow_creates_entry_with_home_assistant_prices_timezone_option(
    hass, enable_custom_integrations
):
    """The unauthenticated ("public prices only") flow also opts new entries into "home_assistant" by default."""
    result = await hass.config_entries.flow.async_init(
        const.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_AUTHENTICATION: False})

    assert result2["type"] == "create_entry"
    assert result2["options"] == {const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}

    entries = hass.config_entries.async_entries(const.DOMAIN)
    assert len(entries) == 1
    assert entries[0].options == {const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}


async def test_login_single_site_creates_entry_with_home_assistant_prices_timezone_option(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """A fresh single-site login also stores options={"prices_timezone": "home_assistant"} on the new entry."""
    site = make_delivery_site("site-1", "IN_DELIVERY", street="Vondelstraat", house_number="7")
    mock_config_flow_api.UserSites = AsyncMock(return_value=make_user_sites([site]))
    mock_config_flow_api.login.return_value = MagicMock(authToken="access-token", refreshToken="refresh-token")
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)

    result = await _start_login_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
    )
    await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert result2["options"] == {const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}

    entries = hass.config_entries.async_entries(const.DOMAIN)
    assert len(entries) == 1
    assert entries[0].options == {const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}


async def test_options_flow_init_defaults_to_utc_for_legacy_entry_without_options(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """The options init form defaults to "utc" for a legacy entry that has no options set at all."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == "form"
    assert result["step_id"] == "init"
    schema = result["data_schema"].schema
    tz_key = next(k for k in schema if getattr(k, "schema", None) == const.CONF_PRICES_TIMEZONE)
    assert tz_key.default() == const.PRICES_TIMEZONE_UTC


async def test_options_flow_init_defaults_to_current_option_for_new_entry(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """The options init form defaults to the entry's currently stored option (e.g. "home_assistant")."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        options={const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    schema = result["data_schema"].schema
    tz_key = next(k for k in schema if getattr(k, "schema", None) == const.CONF_PRICES_TIMEZONE)
    assert tz_key.default() == const.PRICES_TIMEZONE_HOME_ASSISTANT


async def test_options_flow_submit_updates_options_and_reloads_entry_to_loaded(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """Submitting "home_assistant" creates the options entry, updates entry.options, and reloads it to LOADED."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"], {const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}
    )
    await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert entry.options == {const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}
    assert entry.state is ConfigEntryState.LOADED
