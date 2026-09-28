"""Tests for the Frank Energie config flow."""
import pytest
from homeassistant import config_entries
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.frank_energie import const

pytestmark = pytest.mark.asyncio


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
