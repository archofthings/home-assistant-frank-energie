"""Tests for ContractCoordinator (see contract.py)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.exceptions import AuthRequiredException
from python_frank_energie.models import ContractPriceResolutionState

from custom_components.frank_energie import const
from custom_components.frank_energie.contract import ContractCoordinator


def make_connection(segment: str, connection_id: str | None) -> SimpleNamespace:
    """Build a minimal stand-in for a Connection, exposing only what ContractCoordinator reads."""
    return SimpleNamespace(segment=segment, connectionId=connection_id)


def make_user(connections: list[SimpleNamespace]) -> SimpleNamespace:
    """Build a minimal stand-in for a User, exposing only what ContractCoordinator reads."""
    return SimpleNamespace(connections=connections)


def make_state(**overrides) -> ContractPriceResolutionState:
    defaults = dict(
        active_option="PT60M",
        available_options=["PT15M", "PT60M"],
        change_request_effective_date=None,
        is_change_request_possible=True,
        upcoming_change=None,
        upcoming_change_effective_date=None,
    )
    defaults.update(overrides)
    return ContractPriceResolutionState(**defaults)


@pytest.fixture
def entry(hass):
    config_entry = MockConfigEntry(domain=const.DOMAIN, data={"site_reference": "site-1"}, unique_id="frank_energie")
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
def price_coordinator(mock_api):
    """A stand-in for FrankEnergieCoordinator exposing only what ContractCoordinator needs."""
    coordinator = MagicMock()
    coordinator.api = mock_api
    coordinator.site_reference = "site-1"
    return coordinator


@pytest.fixture
def coordinator(hass, entry, price_coordinator):
    return ContractCoordinator(hass, entry, price_coordinator)


async def test_resolves_connection_id_once_and_fetches_state(coordinator, mock_api):
    """The electricity connection id is resolved from user() and used to fetch the price resolution state."""
    mock_api.user.return_value = make_user(
        [make_connection("GAS", "gas-conn"), make_connection("ELECTRICITY", "elec-conn")]
    )
    mock_api.contract_price_resolution_state.return_value = make_state()

    data = await coordinator._async_update_data()

    mock_api.user.assert_awaited_once_with("site-1")
    mock_api.contract_price_resolution_state.assert_awaited_once_with("elec-conn")
    assert data.active_option == "PT60M"
    assert coordinator.connection_id == "elec-conn"

    # A second refresh reuses the cached connection id; user() is not called again.
    await coordinator._async_update_data()
    mock_api.user.assert_awaited_once()


async def test_no_electricity_connection_leaves_data_none_and_retries_next_refresh(coordinator, mock_api):
    """When the account has no electricity connection, data stays None and user() is retried next refresh."""
    mock_api.user.return_value = make_user([make_connection("GAS", "gas-conn")])

    data = await coordinator._async_update_data()

    assert data is None
    mock_api.contract_price_resolution_state.assert_not_awaited()

    mock_api.user.return_value = make_user(
        [make_connection("ELECTRICITY", "elec-conn")]
    )
    mock_api.contract_price_resolution_state.return_value = make_state()

    data = await coordinator._async_update_data()

    assert mock_api.user.await_count == 2
    assert data.active_option == "PT60M"


async def test_user_error_raises_update_failed(coordinator, mock_api):
    """An auth/library error from user() raises UpdateFailed, never ConfigEntryAuthFailed."""
    mock_api.user.side_effect = AuthRequiredException("token expired")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
