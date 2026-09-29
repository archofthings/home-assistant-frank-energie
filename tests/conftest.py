import sys
from os.path import abspath, dirname
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie import FrankEnergie

root_dir = abspath(dirname(__file__) + "/../custom_components/")
sys.path.append(root_dir)

from custom_components.frank_energie import const  # noqa: E402
from tests.utils import FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN  # noqa: E402


@pytest.fixture
def mock_api():
    """An autospec'd mock standing in for a python_frank_energie.FrankEnergie instance.

    Built with create_autospec() so every coroutine method is automatically an
    AsyncMock that enforces the real method's signature (catching tests that
    call/configure it wrong), and nothing here ever hits the real Frank
    Energie API. Individual tests configure the return values/side effects
    they need.
    """
    api = create_autospec(FrankEnergie, instance=True)
    api.is_authenticated = False
    # The coordinator reads api._auth directly (see _async_persist_tokens);
    # default it to None like a real, non-renewed FrankEnergie client so tests
    # don't accidentally persist Mock objects as tokens into the config entry.
    api._auth = None
    api.month_summary = AsyncMock(return_value=None)
    api.invoices = AsyncMock(return_value=None)
    api.period_usage_and_costs = AsyncMock(return_value=None)
    api.month_insights = AsyncMock(return_value=None)
    return api


@pytest.fixture
def mock_frank_energie_class(monkeypatch, mock_api):
    """Patch the FrankEnergie class used by __init__.py to return `mock_api`."""
    monkeypatch.setattr(
        "custom_components.frank_energie.FrankEnergie",
        MagicMock(return_value=mock_api),
    )
    return mock_api


@pytest.fixture
async def config_entry(hass, enable_custom_integrations):
    """A config entry for an unauthenticated (public prices only) account."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def authenticated_config_entry(hass, enable_custom_integrations):
    """A config entry for an authenticated account, site already resolved."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-1",
            CONF_ACCESS_TOKEN: FAKE_ACCESS_TOKEN,
            CONF_TOKEN: FAKE_REFRESH_TOKEN,
        },
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    return entry
