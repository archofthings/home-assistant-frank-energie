import asyncio
import sys
from os.path import abspath, dirname
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.util.async_ import get_scheduled_timer_handles
from pytest_homeassistant_custom_component.common import MockConfigEntry

root_dir = abspath(dirname(__file__) + "/../custom_components/")
sys.path.append(root_dir)

from custom_components.frank_energie import const  # noqa: E402
from tests.utils import FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN  # noqa: E402


@pytest.fixture(autouse=True)
async def _cancel_frank_energie_sensor_timers(hass):
    """Cancel FrankEnergieSensor's self-rescheduled update timers after each test.

    FrankEnergieSensor.async_update() reschedules itself via
    event.async_track_point_in_utc_time on every update, but:
      * it never cancels that callback when the entity/platform is removed
        (no async_will_remove_from_hass override), and
      * the timer is scheduled the moment async_update() first runs, which
        happens even for entity_registry_enabled_default=False entities during
        their initial (pre-"is this entity disabled?") update-before-add, so it
        can leak even for entities that never get added to hass at all.
    This is a production robustness issue (see test report). It also means any
    test that fully sets up the sensor platform would otherwise leak a timer
    past the end of the test, which pytest-homeassistant-custom-component's
    cleanup fixture treats as a hard failure. Clean these up directly at the
    asyncio-loop level so tests can verify normal behaviour without tripping
    over that leak.
    """
    yield
    for handle in list(get_scheduled_timer_handles(hass.loop)):
        if handle.cancelled() or not isinstance(handle, asyncio.TimerHandle):
            continue
        # event.async_track_point_in_utc_time schedules the _TrackPointUTCTime
        # instance itself as the loop callback (with no args), so the HassJob
        # lives on `callback.job`, not in `handle._args`.
        job = getattr(handle._callback, "job", None)
        target = getattr(job, "target", None)
        if getattr(target, "__qualname__", "") == "FrankEnergieSensor._handle_scheduled_update":
            handle.cancel()


@pytest.fixture
def mock_api():
    """A MagicMock standing in for a python_frank_energie.FrankEnergie instance.

    All network-touching coroutine methods are AsyncMocks so nothing here ever
    hits the real Frank Energie API. Individual tests configure the return
    values/side effects they need.
    """
    api = MagicMock(name="FrankEnergieApi")
    api.is_authenticated = False
    api.prices = AsyncMock()
    api.user_prices = AsyncMock()
    api.user_country = AsyncMock()
    api.month_summary = AsyncMock(return_value=None)
    api.invoices = AsyncMock(return_value=None)
    api.UserSites = AsyncMock()
    api.renew_token = AsyncMock()
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
