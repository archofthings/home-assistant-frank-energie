"""Tests for the Frank Energie config flow."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_AUTHENTICATION, CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.exceptions import NetworkError

from custom_components.frank_energie import const
from custom_components.frank_energie.config_flow import _merge_reauth_data, _same_account
from tests.test_init import make_user_sites
from tests.utils import build_market_prices


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
# pointed at adding the other account as a new integration instead (see
# commit b1fd26e for the earlier, since-reverted approach of dropping
# site_reference and accepting the account change).
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
