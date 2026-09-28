"""Tests for Frank Energie diagnostics."""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN, CONF_USERNAME
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from python_frank_energie.models import Invoices, Me, MonthSummary

from custom_components.frank_energie import const, diagnostics
from tests.utils import FAKE_ACCESS_TOKEN, FAKE_REFRESH_TOKEN, build_market_prices

try:
    from pytest_homeassistant_custom_component.components.diagnostics import (
        get_diagnostics_for_config_entry,
    )
except ImportError:  # pragma: no cover - depends on installed test-helper version
    get_diagnostics_for_config_entry = None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def local_midnight():
    """Today's local midnight, as an aware datetime, honoring hass's configured timezone."""
    return dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)


def install_prices(
    mock_api, today_electricity, today_gas, tomorrow_electricity=None, tomorrow_gas=None, resolution_minutes=60
):
    """Configure mock_api.prices to serve today/tomorrow price data."""
    today = local_midnight()
    today_prices = build_market_prices(today, today_electricity, today_gas, resolution_minutes=resolution_minutes)
    tomorrow_prices = build_market_prices(
        today + timedelta(days=1),
        tomorrow_electricity if tomorrow_electricity is not None else [],
        tomorrow_gas if tomorrow_gas is not None else [],
        resolution_minutes=resolution_minutes,
    )

    async def prices_side_effect(start_date, resolution="PT15M"):
        if start_date == dt_util.now().date():
            return today_prices
        return tomorrow_prices

    mock_api.prices.side_effect = prices_side_effect
    return today_prices, tomorrow_prices


def setup_authenticated_api(mock_api, resolution_minutes=60):
    """Configure mock_api for a successful authenticated update cycle."""
    today = local_midnight()
    market_prices = build_market_prices(today, [0.2] * 4, [1.0] * 4, resolution_minutes=resolution_minutes)

    mock_api.is_authenticated = True
    mock_api.user_country.return_value = Me(
        id="user-1",
        email="user@example.com",
        countryCode="NL",
        advancedPaymentAmount=0.0,
        treesCount=0,
        hasInviteLink=False,
        InviteLinkUser=None,
        hasCO2Compensation=False,
        createdAt="2024-01-01T00:00:00Z",
        updatedAt="2024-01-01T00:00:00Z",
        addressHasMultipleSites=False,
        meterReadingExportPeriods=[],
        smartCharging={},
    )
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


async def test_diagnostics_data_counts_resolution_and_has_tomorrow(
    hass, enable_custom_integrations, hass_client, mock_frank_energie_class, config_entry
):
    """The data section reports correct slot counts, resolution and has_tomorrow when tomorrow is available."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    install_prices(
        mock_frank_energie_class,
        [0.10, 0.20, 0.30, 0.40],
        [1.0, 1.1, 1.2, 1.3],
        tomorrow_electricity=[0.50, 0.60, 0.70, 0.80],
        tomorrow_gas=[1.4, 1.5, 1.6, 1.7],
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await get_diag(hass, hass_client, config_entry)

    assert diag["data"]["electricity"]["slot_count"] == 8
    assert diag["data"]["electricity"]["resolution_minutes"] == 60
    assert diag["data"]["electricity"]["has_tomorrow"] is True
    assert diag["data"]["gas"]["slot_count"] == 8
    assert diag["data"]["gas"]["has_tomorrow"] is True

    today = local_midnight()
    first_date_from = datetime.fromisoformat(diag["data"]["electricity"]["first_date_from"])
    last_date_till = datetime.fromisoformat(diag["data"]["electricity"]["last_date_till"])
    # Equal-instant comparison: the diagnostics helper serializes in the Price
    # objects' own (UTC) tzinfo, not necessarily Europe/Amsterdam.
    assert first_date_from == today
    assert last_date_till == today + timedelta(days=1, hours=4)


async def test_diagnostics_data_has_tomorrow_false_without_tomorrow_data(
    hass, enable_custom_integrations, hass_client, mock_frank_energie_class, config_entry
):
    """has_tomorrow is False and slot_count reflects today only, when there is no tomorrow data."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    install_prices(
        mock_frank_energie_class,
        [0.10, 0.20, 0.30, 0.40],
        [1.0, 1.1, 1.2, 1.3],
        tomorrow_electricity=[],
        tomorrow_gas=[],
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await get_diag(hass, hass_client, config_entry)

    assert diag["data"]["electricity"]["slot_count"] == 4
    assert diag["data"]["electricity"]["has_tomorrow"] is False
    assert diag["data"]["gas"]["slot_count"] == 4
    assert diag["data"]["gas"]["has_tomorrow"] is False


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


async def test_diagnostics_prices_timezone_is_utc_for_legacy_entry_without_options(
    hass, enable_custom_integrations, hass_client, mock_frank_energie_class, config_entry
):
    """A legacy entry (config_entry fixture: no options set) reports prices_timezone "utc" in diagnostics."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await get_diag(hass, hass_client, config_entry)

    assert diag["coordinator"]["prices_timezone"] == "utc"


async def test_diagnostics_prices_timezone_is_home_assistant_for_new_entry(
    hass, enable_custom_integrations, hass_client, mock_frank_energie_class, config_entry
):
    """An entry with the "home_assistant" option set reports that value in diagnostics."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    hass.config_entries.async_update_entry(
        config_entry, options={const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}
    )
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await get_diag(hass, hass_client, config_entry)

    assert diag["coordinator"]["prices_timezone"] == "home_assistant"


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


def test_diagnostics_coordinator_reports_last_exception_when_update_failed():
    """When the coordinator's last update failed, last_exception shows class name and message only."""
    coordinator = MagicMock()
    coordinator.last_update_success = False
    coordinator.last_exception = ValueError("boom")
    coordinator.update_interval = timedelta(minutes=60)
    coordinator.user_country = None

    result = diagnostics._diagnostics_coordinator(coordinator)

    assert result["last_update_success"] is False
    assert result["last_exception"] == "ValueError: boom"


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
