"""Tests for the Frank Energie config flow."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_AUTHENTICATION, CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.exceptions import NetworkError

from custom_components.frank_energie import const
from tests.utils import build_market_prices

pytestmark = pytest.mark.asyncio


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
