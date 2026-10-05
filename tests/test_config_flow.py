"""Tests for the Frank Energie config flow."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_AUTHENTICATION, CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.exceptions import AuthException, NetworkError
from python_frank_energie.models import DeliverySite

from custom_components.frank_energie import const
from custom_components.frank_energie.config_flow import (
    SECTION_CHEAPEST_PERIOD,
    SECTION_PRICE_LEVELS,
    SITE_REFERENCE,
    _init_schema,
    _merge_reauth_data,
    _same_account,
)
from tests.utils import (
    build_market_prices,
    configure_authenticated_api as _configure_authenticated_api,
    make_delivery_site,
    make_user_sites,
)


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


async def _start_reauth_flow(hass, entry):
    """Start a SOURCE_REAUTH flow for `entry` and assert it shows the login form."""
    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "login"
    return result


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

    await _start_reauth_flow(hass, entry)


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

    result = await _start_reauth_flow(hass, entry)

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

    result = await _start_reauth_flow(hass, entry)

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

    result = await _start_reauth_flow(hass, entry)

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

    result = await _start_reauth_flow(hass, entry)

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

    result = await _start_reauth_flow(hass, entry)

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

    result = await _start_reauth_flow(hass, entry)

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

    result = await _start_reauth_flow(hass, entry)

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


# Translated text for "wrong_account" (and every other abort reason) is
# covered by tests/test_translations.py; see REQUIRED_KEYS there.


# --------------------------------------------------------------------------
# Unit tests for _same_account() and _merge_reauth_data().
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "stored_username, new_username, expected",
    [
        ("  User@Example.com ", "user@example.com", True),  # case/whitespace insensitive
        ("olduser", "newuser", False),  # different usernames
        (None, "newuser", False),  # no stored username (legacy entry): no account to compare against
    ],
    ids=["case_and_whitespace_insensitive", "different_usernames", "no_stored_username"],
)
def test_same_account(stored_username, new_username, expected):
    assert _same_account(stored_username, new_username) is expected


def test_merge_reauth_data_keeps_site_reference_when_not_dropped():
    """With drop_site_reference=False the existing entry data, including site_reference, is kept."""
    entry_data = {"site_reference": "site-1", CONF_USERNAME: "  User@Example.com "}
    new_data = {CONF_USERNAME: "user@example.com", CONF_ACCESS_TOKEN: "new-token", CONF_TOKEN: "new-refresh"}

    result = _merge_reauth_data(entry_data, new_data, drop_site_reference=False)

    assert result["site_reference"] == "site-1"
    assert result[CONF_USERNAME] == "user@example.com"
    assert result[CONF_ACCESS_TOKEN] == "new-token"
    assert result[CONF_TOKEN] == "new-refresh"


@pytest.mark.parametrize(
    "entry_data",
    [{"site_reference": "site-1"}, {CONF_USERNAME: "olduser"}],
    ids=["with_site_reference", "without_site_reference"],
)
def test_merge_reauth_data_drops_site_reference_when_requested(entry_data):
    """With drop_site_reference=True the old site_reference is dropped, without raising if it was never set."""
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


async def _submit_settings(hass, result, user_input=None):
    """Assert the flow is at the settings step and submit it (the form defaults when no input is given)."""
    assert result["type"] == "form"
    assert result["step_id"] == "settings"
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input or {})


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
    result2 = await _submit_settings(hass, result2)
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
    result2 = await _submit_settings(hass, result2)
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
    result3 = await _submit_settings(hass, result3)
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


@pytest.mark.parametrize(
    "exception, expected_error",
    [
        (AuthException("token rejected"), "invalid_auth"),
        (NetworkError("unreachable"), "cannot_connect"),
    ],
    ids=["auth_exception", "network_error"],
)
async def test_login_usersites_error_shows_login_form_with_error(
    hass, enable_custom_integrations, mock_config_flow_api, exception, expected_error
):
    """An AuthException/NetworkError from UserSites() (after a successful login) re-shows the login form."""
    mock_config_flow_api.UserSites = AsyncMock(side_effect=exception)
    mock_config_flow_api.login.return_value = MagicMock(authToken="access-token", refreshToken="refresh-token")

    result = await _start_login_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
    )

    assert result2["type"] == "form"
    assert result2["step_id"] == "login"
    assert result2["errors"] == {"base": expected_error}


@pytest.mark.parametrize("site_count", [1, 2], ids=["single_site", "multiple_sites"])
async def test_login_duplicate_username_aborts_already_configured(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class, site_count
):
    """Logging in with a username that already has a config entry aborts as already_configured.

    The duplicate check happens before UserSites() is fetched (see W3), so it
    is never awaited -- true whether the account has one site (which would
    otherwise create the entry directly) or several (which would otherwise
    show the multi-site selection step).
    """
    existing = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1", CONF_USERNAME: "user@example.com"},
        unique_id="user@example.com",
    )
    existing.add_to_hass(hass)

    sites = [make_delivery_site(f"site-{i + 1}", "IN_DELIVERY") for i in range(site_count)]
    mock_config_flow_api.UserSites = AsyncMock(return_value=make_user_sites(sites))
    mock_config_flow_api.login.return_value = MagicMock(authToken="access-token", refreshToken="refresh-token")

    result = await _start_login_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
    )

    assert result2["type"] == "abort"
    assert result2["reason"] == "already_configured"
    mock_config_flow_api.UserSites.assert_not_awaited()


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
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """The reconfigure form defaults to the current site; submitting another site updates and reloads the entry.

    The entry is loaded, so the reconfigure flow must reuse the running
    coordinator's own client (`mock_frank_energie_class`) rather than build a
    new one, and must fetch UserSites() exactly once across form + submit.
    """
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
    mock_frank_energie_class.UserSites.return_value = make_user_sites([site1, site2])
    # Simulate the library silently renewing tokens inside UserSites().
    mock_frank_energie_class._auth = MagicMock(authToken="renewed-access-token", refreshToken="renewed-refresh-token")

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

    mock_frank_energie_class.UserSites.assert_awaited_once()


async def test_reconfigure_not_loaded_entry_builds_new_client(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class
):
    """When the entry isn't loaded, reconfigure must build its own client instead of using a coordinator's."""
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
    assert entry.state is ConfigEntryState.NOT_LOADED

    site1 = make_delivery_site("site-1", "IN_DELIVERY")
    site2 = make_delivery_site("site-2", "IN_DELIVERY", street="Newstraat", house_number="99")
    mock_config_flow_api.UserSites = AsyncMock(return_value=make_user_sites([site1, site2]))
    # Unlike mock_frank_energie_class (autospec'd with _auth=None by default), mock_config_flow_api
    # is a plain MagicMock: without this, `._auth` auto-vivifies into a non-None Mock, which
    # _finish_reconfigure would then try (and fail) to persist as real token values.
    mock_config_flow_api._auth = None
    # A successful reconfigure schedules a reload of the entry, which is not yet loaded: configure
    # the (separately mocked) FrankEnergie client used by __init__.py so that reload succeeds too.
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"

    result2 = await hass.config_entries.flow.async_configure(result["flow_id"], {SITE_REFERENCE: "site-2"})
    await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "reconfigure_successful"
    assert entry.data["site_reference"] == "site-2"
    mock_config_flow_api.UserSites.assert_awaited_once()
    mock_frank_energie_class.UserSites.assert_not_awaited()


async def test_reconfigure_first_fetch_failing_aborts_cannot_connect(
    hass, enable_custom_integrations, mock_frank_energie_class
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

    mock_frank_energie_class.UserSites.side_effect = NetworkError("unreachable")

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )

    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"


async def test_reconfigure_no_sites_aborts_no_sites(
    hass, enable_custom_integrations, mock_frank_energie_class
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

    mock_frank_energie_class.UserSites.return_value = make_user_sites([])

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )

    assert result["type"] == "abort"
    assert result["reason"] == "no_sites"


# --------------------------------------------------------------------------
# Regression: the unauthenticated ("public prices only") flow is unchanged.
# --------------------------------------------------------------------------


FEED_IN_DEFAULTS = {
    const.CONF_FEED_IN_MARKUP: const.DEFAULT_FEED_IN_MARKUP,
    const.CONF_SMART_FEED_IN: const.DEFAULT_SMART_FEED_IN,
}


async def test_unauthenticated_flow_creates_entry_with_no_data_and_home_assistant_prices_timezone_option(
    hass, enable_custom_integrations
):
    """Declining to sign in still creates an entry with empty data, and opts it into "home_assistant" by default.

    See commit d6a5dc3, "Add option for the time zone of price times".
    """
    result = await hass.config_entries.flow.async_init(
        const.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_AUTHENTICATION: False})
    result2 = await _submit_settings(hass, result2)

    expected_options = {
        const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT,
        const.CONF_PUBLIC_PRICE_RESOLUTION: const.PUBLIC_PRICE_RESOLUTION_PT15M,
        const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_STATISTICS],
        **FEED_IN_DEFAULTS,
    }
    assert result2["type"] == "create_entry"
    assert result2["data"] == {}
    assert result2["options"] == expected_options

    entries = hass.config_entries.async_entries(const.DOMAIN)
    assert len(entries) == 1
    assert entries[0].options == expected_options


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
    result2 = await _submit_settings(hass, result2)
    await hass.async_block_till_done()

    expected_options = {
        const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT,
        const.CONF_SENSOR_GROUPS: const.DEFAULT_SENSOR_GROUPS,
        **FEED_IN_DEFAULTS,
    }
    assert result2["type"] == "create_entry"
    assert result2["options"] == expected_options

    entries = hass.config_entries.async_entries(const.DOMAIN)
    assert len(entries) == 1
    assert entries[0].options == expected_options


async def _start_public_settings(hass):
    """Start a flow without signing in and return the settings form."""
    result = await hass.config_entries.flow.async_init(
        const.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_AUTHENTICATION: False})


async def test_public_flow_stores_chosen_resolution_and_groups(hass, enable_custom_integrations):
    """The settings step stores the chosen time zone, price resolution, sensor groups and feed-in settings."""
    result = await _start_public_settings(hass)
    result2 = await _submit_settings(
        hass,
        result,
        {
            const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_UTC,
            const.CONF_PUBLIC_PRICE_RESOLUTION: const.PUBLIC_PRICE_RESOLUTION_PT60M,
            const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_UPCOMING, const.SENSOR_GROUP_DAILY_STATISTICS],
            const.CONF_FEED_IN_MARKUP: -0.02,
            const.CONF_SMART_FEED_IN: True,
        },
    )

    assert result2["type"] == "create_entry"
    assert result2["options"] == {
        const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_UTC,
        const.CONF_PUBLIC_PRICE_RESOLUTION: const.PUBLIC_PRICE_RESOLUTION_PT60M,
        const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_UPCOMING, const.SENSOR_GROUP_DAILY_STATISTICS],
        const.CONF_FEED_IN_MARKUP: -0.02,
        const.CONF_SMART_FEED_IN: True,
    }


@pytest.mark.parametrize("logged_in", [False, True], ids=["public", "logged_in"])
async def test_settings_form_fields_depend_on_login(
    hass, enable_custom_integrations, mock_config_flow_api, mock_frank_energie_class, logged_in
):
    """Only a public entry gets the price resolution field; only a logged-in one is offered the login-only groups."""
    if logged_in:
        site = make_delivery_site("site-1", "IN_DELIVERY")
        mock_config_flow_api.UserSites = AsyncMock(return_value=make_user_sites([site]))
        mock_config_flow_api.login.return_value = MagicMock(authToken="access-token", refreshToken="refresh-token")
        result = await _start_login_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
        )
    else:
        result = await _start_public_settings(hass)

    assert result["step_id"] == "settings"
    schema = result["data_schema"].schema
    keys = {getattr(k, "schema", None): k for k in schema}
    assert (const.CONF_PUBLIC_PRICE_RESOLUTION in keys) is (not logged_in)
    offered = set(schema[keys[const.CONF_SENSOR_GROUPS]].config["options"])
    assert (const.SENSOR_GROUPS_REQUIRE_LOGIN[0] in offered) is logged_in
    assert keys[const.CONF_PRICES_TIMEZONE].default() == const.PRICES_TIMEZONE_HOME_ASSISTANT


async def test_settings_step_with_price_analysis_continues_to_analysis_step(hass, enable_custom_integrations):
    """Ticking price_analysis leads to the analysis step; invalid thresholds are rejected, valid ones are stored."""
    result = await _start_public_settings(hass)
    result2 = await _submit_settings(
        hass,
        result,
        {
            const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT,
            const.CONF_PUBLIC_PRICE_RESOLUTION: const.PUBLIC_PRICE_RESOLUTION_PT15M,
            const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_PRICE_ANALYSIS],
        },
    )
    assert result2["type"] == "form"
    assert result2["step_id"] == "analysis"

    def analysis_input(cheap, expensive):
        return {
            SECTION_PRICE_LEVELS: {
                const.CONF_CHEAP_PRICE_THRESHOLD: cheap,
                const.CONF_EXPENSIVE_PRICE_THRESHOLD: expensive,
                const.CONF_SOLAR_THRESHOLD_KWH: 1.5,
            },
            SECTION_CHEAPEST_PERIOD: {
                const.CONF_CHEAPEST_PERIOD_MINUTES: 120.0,
                const.CONF_CHEAPEST_PERIOD_ONLY_WHEN_CHEAP: True,
            },
        }

    result3 = await hass.config_entries.flow.async_configure(result2["flow_id"], analysis_input(0.40, 0.40))
    assert result3["type"] == "form"
    assert result3["step_id"] == "analysis"
    assert result3["errors"] == {"base": "thresholds_invalid"}

    result4 = await hass.config_entries.flow.async_configure(result3["flow_id"], analysis_input(0.20, 0.40))

    assert result4["type"] == "create_entry"
    assert result4["options"] == {
        const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT,
        const.CONF_PUBLIC_PRICE_RESOLUTION: const.PUBLIC_PRICE_RESOLUTION_PT15M,
        const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_PRICE_ANALYSIS],
        const.CONF_CHEAP_PRICE_THRESHOLD: 0.20,
        const.CONF_EXPENSIVE_PRICE_THRESHOLD: 0.40,
        const.CONF_SOLAR_THRESHOLD_KWH: 1.5,
        const.CONF_CHEAPEST_PERIOD_MINUTES: 120,
        const.CONF_CHEAPEST_PERIOD_ONLY_WHEN_CHEAP: True,
        **FEED_IN_DEFAULTS,
    }
    assert isinstance(result4["options"][const.CONF_CHEAPEST_PERIOD_MINUTES], int)


async def test_duplicate_public_entry_aborts_before_the_settings_form(hass, enable_custom_integrations):
    """A second public entry aborts before the user is asked for any settings."""
    MockConfigEntry(domain=const.DOMAIN, data={}, unique_id="frank_energie").add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        const.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_AUTHENTICATION: False})

    assert result2["type"] == "abort"
    assert result2["reason"] in ("already_configured", "single_instance_allowed")


@pytest.mark.parametrize(
    "options, expected_default",
    [
        ({}, const.PRICES_TIMEZONE_UTC),
        ({const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}, const.PRICES_TIMEZONE_HOME_ASSISTANT),
    ],
    ids=["legacy_entry_without_options", "entry_with_stored_option"],
)
async def test_options_flow_init_defaults_to_the_entrys_current_option(
    hass, enable_custom_integrations, mock_frank_energie_class, options, expected_default
):
    """The options init form defaults to "utc" for a legacy entry, or the entry's currently stored option."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        options=options,
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
    assert tz_key.default() == expected_default


async def test_options_flow_submit_updates_options_and_reloads_entry_to_loaded(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """Submitting both option pages updates entry.options (incl. sensor_groups) and reloads it to LOADED."""
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
        result["flow_id"],
        {
            const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT,
            const.CONF_PUBLIC_PRICE_RESOLUTION: const.PUBLIC_PRICE_RESOLUTION_PT60M,
            const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_PRICE_ANALYSIS],
            const.CONF_FEED_IN_MARKUP: -0.02,
            const.CONF_SMART_FEED_IN: True,
        },
    )
    assert result2["type"] == "form"
    assert result2["step_id"] == "analysis"

    result3 = await hass.config_entries.options.async_configure(
        result2["flow_id"],
        {
            SECTION_PRICE_LEVELS: {
                const.CONF_CHEAP_PRICE_THRESHOLD: const.DEFAULT_CHEAP_PRICE_THRESHOLD,
                const.CONF_EXPENSIVE_PRICE_THRESHOLD: const.DEFAULT_EXPENSIVE_PRICE_THRESHOLD,
                const.CONF_SOLAR_THRESHOLD_KWH: const.DEFAULT_SOLAR_THRESHOLD_KWH,
            },
            SECTION_CHEAPEST_PERIOD: {
                const.CONF_CHEAPEST_PERIOD_MINUTES: const.DEFAULT_CHEAPEST_PERIOD_MINUTES,
                const.CONF_CHEAPEST_PERIOD_ONLY_WHEN_CHEAP: True,
            },
        },
    )
    await hass.async_block_till_done()

    assert result3["type"] == "create_entry"
    assert entry.options == {
        const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT,
        const.CONF_PUBLIC_PRICE_RESOLUTION: const.PUBLIC_PRICE_RESOLUTION_PT60M,
        # "costs" is kept: this entry is public (no access token) and had it
        # enabled by default (legacy entry, no options), so it's added back
        # even though it wasn't offered as a choice (see config_flow.py).
        const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_PRICE_ANALYSIS, const.SENSOR_GROUP_COSTS],
        const.CONF_CHEAP_PRICE_THRESHOLD: const.DEFAULT_CHEAP_PRICE_THRESHOLD,
        const.CONF_EXPENSIVE_PRICE_THRESHOLD: const.DEFAULT_EXPENSIVE_PRICE_THRESHOLD,
        const.CONF_CHEAPEST_PERIOD_MINUTES: const.DEFAULT_CHEAPEST_PERIOD_MINUTES,
        const.CONF_CHEAPEST_PERIOD_ONLY_WHEN_CHEAP: True,
        const.CONF_SOLAR_THRESHOLD_KWH: const.DEFAULT_SOLAR_THRESHOLD_KWH,
        # Feed-in settings survive the analysis page.
        const.CONF_FEED_IN_MARKUP: -0.02,
        const.CONF_SMART_FEED_IN: True,
    }
    assert entry.state is ConfigEntryState.LOADED


async def test_options_flow_without_price_analysis_creates_entry_directly_and_keeps_stored_analysis_options(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """Not selecting price_analysis skips the "analysis" page, but keeps any previously stored analysis options."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        options={
            const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_UTC,
            const.CONF_SENSOR_GROUPS: list(const.LEGACY_SENSOR_GROUPS),
            const.CONF_CHEAP_PRICE_THRESHOLD: 0.30,
            const.CONF_EXPENSIVE_PRICE_THRESHOLD: 0.45,
            const.CONF_CHEAPEST_PERIOD_MINUTES: 90,
            const.CONF_SOLAR_THRESHOLD_KWH: 2.0,
            const.CONF_FEED_IN_MARKUP: -0.03,
            const.CONF_SMART_FEED_IN: True,
        },
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT,
            const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_UPCOMING],
        },
    )
    await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert entry.options == {
        const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT,
        const.CONF_PUBLIC_PRICE_RESOLUTION: const.DEFAULT_PUBLIC_PRICE_RESOLUTION,
        # "costs" is kept: this entry is public (no access token) and had it
        # stored/enabled, so it's added back even though it wasn't offered
        # as a choice (see config_flow.py).
        const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_UPCOMING, const.SENSOR_GROUP_COSTS],
        const.CONF_CHEAP_PRICE_THRESHOLD: 0.30,
        const.CONF_EXPENSIVE_PRICE_THRESHOLD: 0.45,
        const.CONF_CHEAPEST_PERIOD_MINUTES: 90,
        const.CONF_SOLAR_THRESHOLD_KWH: 2.0,
        const.CONF_FEED_IN_MARKUP: -0.03,
        const.CONF_SMART_FEED_IN: True,
    }
    assert entry.state is ConfigEntryState.LOADED


async def test_options_flow_rejects_cheap_threshold_not_below_expensive(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """Submitting cheap >= expensive on the analysis page re-shows it with a thresholds_invalid error, unsaved."""
    entry = MockConfigEntry(domain=const.DOMAIN, data={"site_reference": "site-1"}, unique_id="frank_energie")
    entry.add_to_hass(hass)
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_UTC,
            const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_PRICE_ANALYSIS],
        },
    )
    assert result2["step_id"] == "analysis"

    result3 = await hass.config_entries.options.async_configure(
        result2["flow_id"],
        {
            SECTION_PRICE_LEVELS: {
                const.CONF_CHEAP_PRICE_THRESHOLD: 0.40,
                const.CONF_EXPENSIVE_PRICE_THRESHOLD: 0.40,
                const.CONF_SOLAR_THRESHOLD_KWH: 1.5,
            },
            SECTION_CHEAPEST_PERIOD: {
                const.CONF_CHEAPEST_PERIOD_MINUTES: 120,
            },
        },
    )

    assert result3["type"] == "form"
    assert result3["step_id"] == "analysis"
    assert result3["errors"] == {"base": "thresholds_invalid"}
    assert const.CONF_CHEAP_PRICE_THRESHOLD not in entry.options


async def test_options_flow_submitting_without_solar_forecast_entry_clears_it(
    hass, enable_custom_integrations, mock_frank_energie_class, monkeypatch
):
    """Submitting the analysis page without solar_forecast_entry removes a previously configured choice (C3).

    The SelectSelector previously had a `default=` whenever a choice was
    configured, so an omitted key (the frontend's way of clearing a
    SelectSelector) had voluptuous put the old default straight back,
    making the option impossible to clear.
    """
    solar_entry = MockConfigEntry(domain="fake_solar", title="My Roof", unique_id="solar-1")
    solar_entry.add_to_hass(hass)

    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        options={const.CONF_SOLAR_FORECAST_ENTRY: solar_entry.entry_id},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)

    async def fake_get_energy_platforms(_hass):
        return {"fake_solar": AsyncMock(return_value={"wh_hours": {}})}

    monkeypatch.setattr(
        "homeassistant.components.energy.websocket_api.async_get_energy_platforms",
        fake_get_energy_platforms,
    )

    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_UTC,
            const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_PRICE_ANALYSIS],
        },
    )
    assert result2["step_id"] == "analysis"

    result3 = await hass.config_entries.options.async_configure(
        result2["flow_id"],
        {
            SECTION_PRICE_LEVELS: {
                const.CONF_CHEAP_PRICE_THRESHOLD: 0.25,
                const.CONF_EXPENSIVE_PRICE_THRESHOLD: 0.40,
                const.CONF_SOLAR_THRESHOLD_KWH: 1.5,
                # CONF_SOLAR_FORECAST_ENTRY intentionally omitted: clearing the selector.
            },
            SECTION_CHEAPEST_PERIOD: {
                const.CONF_CHEAPEST_PERIOD_MINUTES: 120,
            },
        },
    )
    await hass.async_block_till_done()

    assert result3["type"] == "create_entry"
    assert const.CONF_SOLAR_FORECAST_ENTRY not in entry.options


async def test_options_flow_init_does_not_offer_costs_group_for_a_public_entry(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """The sensor_groups selector for a public (not logged in) entry does not offer "costs" as a choice."""
    entry = MockConfigEntry(domain=const.DOMAIN, data={"site_reference": "site-1"}, unique_id="frank_energie")
    entry.add_to_hass(hass)
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    schema = result["data_schema"].schema
    groups_key = next(k for k in schema if getattr(k, "schema", None) == const.CONF_SENSOR_GROUPS)
    offered_options = schema[groups_key].config["options"]
    assert const.SENSOR_GROUP_COSTS not in offered_options


@pytest.mark.parametrize(
    "group", [const.SENSOR_GROUP_DAILY_USAGE, const.SENSOR_GROUP_MONTHLY_USAGE], ids=["daily_usage", "monthly_usage"]
)
async def test_options_flow_init_does_not_offer_usage_groups_for_a_public_entry(
    hass, enable_custom_integrations, mock_frank_energie_class, group
):
    """The sensor_groups selector for a public entry does not offer daily_usage/monthly_usage as a choice."""
    entry = MockConfigEntry(domain=const.DOMAIN, data={"site_reference": "site-1"}, unique_id="frank_energie")
    entry.add_to_hass(hass)
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)

    schema = result["data_schema"].schema
    groups_key = next(k for k in schema if getattr(k, "schema", None) == const.CONF_SENSOR_GROUPS)
    offered_options = schema[groups_key].config["options"]
    assert group not in offered_options


@pytest.mark.parametrize(
    "options",
    [
        {},
        {const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_STATISTICS, const.SENSOR_GROUP_COSTS]},
    ],
    ids=["legacy_entry_without_options", "entry_with_stored_costs"],
)
async def test_options_flow_submit_keeps_costs_for_a_public_entry(
    hass, enable_custom_integrations, mock_frank_energie_class, options
):
    """Submitting the options form's own defaults succeeds for a public entry and keeps "costs" stored.

    "costs" is left out of the sensor_groups choices offered to a public
    (not logged in) entry (see the previous test), but was still the default
    selection whenever it was part of the entry's currently stored/effective
    groups (a legacy entry with no options defaults to all groups, including
    "costs"). SelectSelector validates every submitted item against the
    offered options, so submitting the form's own default used to fail.
    """
    entry = MockConfigEntry(
        domain=const.DOMAIN, data={"site_reference": "site-1"}, options=options, unique_id="frank_energie"
    )
    entry.add_to_hass(hass)
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    tz_key = next(k for k in schema if getattr(k, "schema", None) == const.CONF_PRICES_TIMEZONE)
    groups_key = next(k for k in schema if getattr(k, "schema", None) == const.CONF_SENSOR_GROUPS)

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {const.CONF_PRICES_TIMEZONE: tz_key.default(), const.CONF_SENSOR_GROUPS: groups_key.default()},
    )

    if result2["type"] == "form":
        assert result2["step_id"] == "analysis"
        result2 = await hass.config_entries.options.async_configure(
            result2["flow_id"],
            {
                SECTION_PRICE_LEVELS: {
                    const.CONF_CHEAP_PRICE_THRESHOLD: const.DEFAULT_CHEAP_PRICE_THRESHOLD,
                    const.CONF_EXPENSIVE_PRICE_THRESHOLD: const.DEFAULT_EXPENSIVE_PRICE_THRESHOLD,
                    const.CONF_SOLAR_THRESHOLD_KWH: const.DEFAULT_SOLAR_THRESHOLD_KWH,
                },
                SECTION_CHEAPEST_PERIOD: {
                    const.CONF_CHEAPEST_PERIOD_MINUTES: const.DEFAULT_CHEAPEST_PERIOD_MINUTES,
                },
            },
        )

    assert result2["type"] == "create_entry"
    assert const.SENSOR_GROUP_COSTS in entry.options[const.CONF_SENSOR_GROUPS]


async def test_options_flow_solar_forecast_entry_lists_entries_with_a_solar_forecast_platform(
    hass, enable_custom_integrations, mock_frank_energie_class, monkeypatch
):
    """The solar_forecast_entry selector only lists entries whose domain provides a solar forecast platform."""
    entry = MockConfigEntry(domain=const.DOMAIN, data={"site_reference": "site-1"}, unique_id="frank_energie")
    entry.add_to_hass(hass)
    mock_frank_energie_class.prices.return_value = build_market_prices(dt_util.now(), [0.2] * 24, [1.0] * 24)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    solar_entry = MockConfigEntry(domain="fake_solar", title="My Roof", unique_id="solar-1")
    solar_entry.add_to_hass(hass)
    other_entry = MockConfigEntry(domain="fake_other", title="Not solar", unique_id="other-1")
    other_entry.add_to_hass(hass)

    async def fake_get_energy_platforms(_hass):
        return {"fake_solar": AsyncMock(return_value={"wh_hours": {}})}

    monkeypatch.setattr(
        "homeassistant.components.energy.websocket_api.async_get_energy_platforms",
        fake_get_energy_platforms,
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_UTC,
            const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_PRICE_ANALYSIS],
        },
    )
    assert result2["step_id"] == "analysis"

    schema = result2["data_schema"].schema
    price_levels_key = next(k for k in schema if getattr(k, "schema", None) == SECTION_PRICE_LEVELS)
    section_schema = schema[price_levels_key].schema.schema
    solar_key = next(k for k in section_schema if getattr(k, "schema", None) == const.CONF_SOLAR_FORECAST_ENTRY)
    options = section_schema[solar_key].config["options"]
    assert {opt["value"] for opt in options} == {solar_entry.entry_id}
    assert options[0]["label"] == "My Roof (fake_solar)"


@pytest.mark.parametrize("logged_in", [False, True], ids=["public", "logged_in"])
def test_init_schema_offers_public_price_resolution_only_when_not_logged_in(logged_in):
    """The price resolution field is only part of the init form for a public entry."""
    schema = _init_schema({}, logged_in).schema
    keys = {getattr(k, "schema", None) for k in schema}
    assert (const.CONF_PUBLIC_PRICE_RESOLUTION in keys) is not logged_in
