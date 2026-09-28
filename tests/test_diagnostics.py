"""Tests for Frank Energie diagnostics."""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.exceptions import NetworkError
from python_frank_energie.models import Invoices

from custom_components.frank_energie import const, diagnostics
from tests.utils import (
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    build_market_prices,
    install_prices,
    local_midnight,
    make_me,
    make_month_summary,
)

try:
    from pytest_homeassistant_custom_component.components.diagnostics import (
        get_diagnostics_for_config_entry,
    )
except ImportError:  # pragma: no cover - depends on installed test-helper version
    get_diagnostics_for_config_entry = None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def setup_authenticated_api(mock_api, resolution_minutes=60):
    """Configure mock_api for a successful authenticated update cycle."""
    today = local_midnight()
    market_prices = build_market_prices(today, [0.2] * 4, [1.0] * 4, resolution_minutes=resolution_minutes)

    mock_api.is_authenticated = True
    mock_api.user_country.return_value = make_me("NL")
    mock_api.user_prices.return_value = market_prices
    mock_api.month_summary.return_value = make_month_summary()
    mock_api.invoices.return_value = Invoices.empty()


async def get_diag(hass, hass_client, entry):
    """Fetch diagnostics via the HTTP helper when available, else call the module function directly."""
    if get_diagnostics_for_config_entry is not None:
        return await get_diagnostics_for_config_entry(hass, hass_client, entry)
    return await diagnostics.async_get_config_entry_diagnostics(hass, entry)


# --------------------------------------------------------------------------
# Redaction: tokens, username, site_reference, title, unique_id; no address
# --------------------------------------------------------------------------


async def test_diagnostics_redacts_sensitive_fields_and_hides_address(
    hass, enable_custom_integrations, hass_client, mock_frank_energie_class
):
    """Tokens, username, site_reference, title and unique_id are redacted; no address leaks anywhere."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-42",
            CONF_USERNAME: "someone@example.com",
            CONF_ACCESS_TOKEN: FAKE_ACCESS_TOKEN,
            CONF_TOKEN: FAKE_REFRESH_TOKEN,
        },
        unique_id="someone@example.com",
        title="Vondelstraat 7",
    )
    entry.add_to_hass(hass)

    setup_authenticated_api(mock_frank_energie_class)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await get_diag(hass, hass_client, entry)

    assert diag["entry"]["data"][CONF_ACCESS_TOKEN] == "**REDACTED**"
    assert diag["entry"]["data"][CONF_TOKEN] == "**REDACTED**"
    assert diag["entry"]["data"][CONF_USERNAME] == "**REDACTED**"
    assert diag["entry"]["data"]["site_reference"] == "**REDACTED**"
    assert diag["entry"]["title"] == "**REDACTED**"
    assert diag["entry"]["unique_id"] == "**REDACTED**"

    serialized = json.dumps(diag)
    assert "Vondelstraat" not in serialized
    assert FAKE_ACCESS_TOKEN not in serialized
    assert FAKE_REFRESH_TOKEN not in serialized
    assert "someone@example.com" not in serialized
    assert "site-42" not in serialized


# --------------------------------------------------------------------------
# W1: entry not loaded yet (first refresh failed, e.g. SETUP_RETRY)
# --------------------------------------------------------------------------


async def test_diagnostics_works_when_first_refresh_failed_and_entry_not_loaded(
    hass, enable_custom_integrations, hass_client, mock_frank_energie_class, config_entry
):
    """When the first refresh fails and the entry is left in SETUP_RETRY, diagnostics must not raise KeyError.

    hass.data[DOMAIN][entry_id] is only populated after a successful first
    refresh; report the redacted "entry" section with coordinator/data set to
    None instead.
    """
    mock_frank_energie_class.prices.side_effect = NetworkError("network unreachable")

    result = await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert result is False
    assert config_entry.state is ConfigEntryState.SETUP_RETRY

    diag = await get_diag(hass, hass_client, config_entry)

    assert diag["coordinator"] is None
    assert diag["data"] is None
    assert diag["entry"]["data"]["site_reference"] == "**REDACTED**"


# --------------------------------------------------------------------------
# Coordinator section
# --------------------------------------------------------------------------


async def test_diagnostics_coordinator_section(
    hass, enable_custom_integrations, hass_client, mock_frank_energie_class, authenticated_config_entry
):
    """The coordinator section reports last_update_success, update_interval and user_country."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    setup_authenticated_api(mock_frank_energie_class)

    assert await hass.config_entries.async_setup(authenticated_config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await get_diag(hass, hass_client, authenticated_config_entry)

    assert diag["coordinator"]["last_update_success"] is True
    assert diag["coordinator"]["last_exception"] is None
    assert diag["coordinator"]["update_interval"] == timedelta(minutes=60).total_seconds()
    assert diag["coordinator"]["user_country"] == "NL"


# --------------------------------------------------------------------------
# Data counts, resolution and has_tomorrow
# --------------------------------------------------------------------------


@pytest.mark.parametrize("has_tomorrow", [True, False], ids=["with_tomorrow", "without_tomorrow"])
async def test_diagnostics_data_counts_resolution_and_has_tomorrow(
    hass, enable_custom_integrations, hass_client, mock_frank_energie_class, config_entry, has_tomorrow
):
    """The data section reports correct slot counts, resolution and has_tomorrow, with/without tomorrow data."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    install_prices(
        mock_frank_energie_class,
        [0.10, 0.20, 0.30, 0.40],
        [1.0, 1.1, 1.2, 1.3],
        tomorrow_electricity=[0.50, 0.60, 0.70, 0.80] if has_tomorrow else [],
        tomorrow_gas=[1.4, 1.5, 1.6, 1.7] if has_tomorrow else [],
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await get_diag(hass, hass_client, config_entry)

    expected_slot_count = 8 if has_tomorrow else 4
    assert diag["data"]["electricity"]["slot_count"] == expected_slot_count
    assert diag["data"]["electricity"]["resolution_minutes"] == 60
    assert diag["data"]["electricity"]["has_tomorrow"] is has_tomorrow
    assert diag["data"]["gas"]["slot_count"] == expected_slot_count
    assert diag["data"]["gas"]["has_tomorrow"] is has_tomorrow

    if has_tomorrow:
        today = local_midnight()
        first_date_from = datetime.fromisoformat(diag["data"]["electricity"]["first_date_from"])
        last_date_till = datetime.fromisoformat(diag["data"]["electricity"]["last_date_till"])
        # Equal-instant comparison: the diagnostics helper serializes in the
        # Price objects' own (UTC) tzinfo, not necessarily Europe/Amsterdam.
        assert first_date_from == today
        assert last_date_till == today + timedelta(days=1, hours=4)


async def test_diagnostics_month_summary_and_invoices_availability(
    hass, enable_custom_integrations, hass_client, mock_frank_energie_class, config_entry
):
    """month_summary_available/invoices_available are False for an unauthenticated entry."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await get_diag(hass, hass_client, config_entry)

    assert diag["data"]["month_summary_available"] is False
    assert diag["data"]["invoices_available"] is False


# --------------------------------------------------------------------------
# prices_timezone (see commit d6a5dc3, "Add option for the time zone of
# price times").
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "options, expected_prices_timezone",
    [({}, "utc"), ({const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}, "home_assistant")],
    ids=["legacy_entry_without_options", "entry_with_home_assistant_option"],
)
async def test_diagnostics_prices_timezone_follows_the_entrys_option(
    hass, enable_custom_integrations, hass_client, mock_frank_energie_class, config_entry,
    options, expected_prices_timezone
):
    """A legacy entry (no options set) reports "utc"; an entry with the "home_assistant" option reports that."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    if options:
        hass.config_entries.async_update_entry(config_entry, options=options)
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await get_diag(hass, hass_client, config_entry)

    assert diag["coordinator"]["prices_timezone"] == expected_prices_timezone


# --------------------------------------------------------------------------
# last_exception: class name and message only, never a full traceback
# --------------------------------------------------------------------------


def test_serialize_exception_returns_none_for_no_exception():
    """No exception serializes to None."""
    assert diagnostics._serialize_exception(None) is None


def test_serialize_exception_class_name_and_message_only():
    """An exception serializes to 'ClassName: message', with no traceback."""
    try:
        raise RuntimeError("update failed: network unreachable")
    except RuntimeError as ex:
        result = diagnostics._serialize_exception(ex)

    assert result == "RuntimeError: update failed: network unreachable"
    assert "Traceback" not in result
    assert "File \"" not in result


def test_serialize_exception_redacts_entry_tokens_username_and_site_reference():
    """A message echoing back the entry's tokens/username/site_reference has those values redacted."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-42",
            CONF_USERNAME: "someone@example.com",
            CONF_ACCESS_TOKEN: FAKE_ACCESS_TOKEN,
            CONF_TOKEN: FAKE_REFRESH_TOKEN,
        },
    )
    message = (
        f"request failed for user {entry.data[CONF_USERNAME]} "
        f"(site {entry.data['site_reference']}, token {entry.data[CONF_ACCESS_TOKEN]}/{entry.data[CONF_TOKEN]})"
    )

    try:
        raise RuntimeError(message)
    except RuntimeError as ex:
        result = diagnostics._serialize_exception(ex, entry)

    assert "someone@example.com" not in result
    assert "site-42" not in result
    assert FAKE_ACCESS_TOKEN not in result
    assert FAKE_REFRESH_TOKEN not in result
    assert result.count("**REDACTED**") == 4


def test_diagnostics_coordinator_reports_last_exception_when_update_failed():
    """When the coordinator's last update failed, last_exception shows class name and message only."""
    coordinator = MagicMock()
    coordinator.last_update_success = False
    coordinator.last_exception = ValueError("boom")
    coordinator.update_interval = timedelta(minutes=60)
    coordinator.user_country = None
    coordinator.entry = MockConfigEntry(domain=const.DOMAIN, data={})

    result = diagnostics._diagnostics_coordinator(coordinator)

    assert result["last_update_success"] is False
    assert result["last_exception"] == "ValueError: boom"


async def test_diagnostics_redacts_entry_values_from_last_exception_end_to_end(
    hass, enable_custom_integrations, hass_client, mock_frank_energie_class, authenticated_config_entry
):
    """End-to-end: an update error echoing the site_reference has it redacted in the diagnostics response."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])
    assert await hass.config_entries.async_setup(authenticated_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[const.DOMAIN][authenticated_config_entry.entry_id][const.CONF_COORDINATOR]
    try:
        raise RuntimeError(f"user-error: request failed for site {authenticated_config_entry.data['site_reference']}")
    except RuntimeError as ex:
        coordinator.last_exception = ex
        coordinator.last_update_success = False

    diag = await get_diag(hass, hass_client, authenticated_config_entry)

    assert "site-1" not in diag["coordinator"]["last_exception"]
    assert "**REDACTED**" in diag["coordinator"]["last_exception"]


def test_diagnostics_data_section_when_coordinator_data_is_none():
    """When coordinator.data is None (e.g. before first refresh), the data section reports empty/zero values."""
    coordinator = MagicMock()
    coordinator.data = None

    result = diagnostics._diagnostics_data(coordinator)

    assert result["electricity"]["slot_count"] == 0
    assert result["electricity"]["has_tomorrow"] is False
    assert result["electricity"]["first_date_from"] is None
    assert result["electricity"]["last_date_till"] is None
    assert result["gas"]["slot_count"] == 0
    assert result["month_summary_available"] is False
    assert result["invoices_available"] is False
