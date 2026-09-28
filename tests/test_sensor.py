"""Tests for Frank Energie sensors."""
from datetime import datetime, timedelta, timezone

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from python_frank_energie.models import Invoice, Invoices, Me, MonthSummary

from custom_components.frank_energie import const, sensor
from custom_components.frank_energie.sensor import next_quarter_hour
from tests.utils import build_market_prices, price_generator

# NOTE: no module-level `pytestmark = pytest.mark.asyncio` here (unlike the
# other test modules) because this file also contains plain sync tests for
# next_quarter_hour(); pytest-asyncio's asyncio_mode=auto (see pytest.ini)
# already detects the async def tests below without needing the marker.


# --------------------------------------------------------------------------
# next_quarter_hour: pure function, no hass/mocking required
# --------------------------------------------------------------------------

def test_next_quarter_hour_mid_interval():
    now = datetime(2024, 1, 1, 10, 7, 31, 500000, tzinfo=timezone.utc)
    assert next_quarter_hour(now) == datetime(2024, 1, 1, 10, 15, 0, tzinfo=timezone.utc)


def test_next_quarter_hour_on_boundary():
    now = datetime(2024, 1, 1, 10, 15, 0, tzinfo=timezone.utc)
    assert next_quarter_hour(now) == datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc)


def test_next_quarter_hour_end_of_hour():
    now = datetime(2024, 1, 1, 10, 59, 30, tzinfo=timezone.utc)
    assert next_quarter_hour(now) == datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc)


def test_next_quarter_hour_end_of_day():
    now = datetime(2024, 1, 1, 23, 50, 0, tzinfo=timezone.utc)
    assert next_quarter_hour(now) == datetime(2024, 1, 2, 0, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def entity_id_for_key(hass, entry, key: str) -> str | None:
    """Look up an entity_id by its unique_id (f'{entry.unique_id}.{key}'), independent of slugging."""
    return er.async_get(hass).async_get_entity_id("sensor", const.DOMAIN, f"{entry.unique_id}.{key}")


def state_for_key(hass, entry, key: str) -> State | None:
    """Return the current state object for a sensor by its description key."""
    entity_id = entity_id_for_key(hass, entry, key)
    return hass.states.get(entity_id) if entity_id else None


async def enable_all_sensors(hass, entry):
    """Enable all disabled-by-default sensors of the integration and let them update."""
    entity_registry = er.async_get(hass)
    for sensor_type in sensor.SENSOR_TYPES:
        if sensor_type.entity_registry_enabled_default is False:
            entity_id = entity_id_for_key(hass, entry, sensor_type.key)
            assert entity_id is not None, f"no registered entity for key={sensor_type.key}"
            entity_registry.async_update_entity(entity_id, disabled_by=None)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1), fire_all=True)
    await hass.async_block_till_done()


def make_invoice(total: float, start: datetime, description: str) -> Invoice:
    return Invoice(id="inv-1", StartDate=start, PeriodDescription=description, TotalAmount=total)


def make_month_summary(**overrides) -> MonthSummary:
    defaults = dict(
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
    defaults.update(overrides)
    return MonthSummary(**defaults)


def make_me(country_code: str = "NL") -> Me:
    return Me(
        id="user-1",
        email="user@example.com",
        countryCode=country_code,
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


def local_midnight():
    """Today's local midnight, as an aware datetime, honoring hass's configured timezone."""
    return dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)


def install_public_prices(mock_api, today_electricity, today_gas, tomorrow_electricity=None, tomorrow_gas=None):
    """Configure mock_api.prices to serve today/tomorrow PT15M price data."""
    today = local_midnight()
    today_prices = build_market_prices(today, today_electricity, today_gas, resolution_minutes=15)
    tomorrow_prices = build_market_prices(
        today + timedelta(days=1),
        tomorrow_electricity if tomorrow_electricity is not None else [0.3] * 96,
        tomorrow_gas if tomorrow_gas is not None else [1.2] * 96,
        resolution_minutes=15,
    )

    async def prices_side_effect(start_date, resolution="PT15M"):
        if start_date == dt_util.now().date():
            return today_prices
        return tomorrow_prices

    mock_api.prices.side_effect = prices_side_effect
    return today_prices, tomorrow_prices


def setup_authenticated_api(mock_api, invoices: Invoices, month_summary=None):
    """Configure mock_api for a successful authenticated update cycle."""
    today = local_midnight()
    market_prices = build_market_prices(today, [0.2] * 96, [1.0] * 96, resolution_minutes=15)

    mock_api.is_authenticated = True
    mock_api.user_country.return_value = make_me("NL")
    mock_api.user_prices.return_value = market_prices
    mock_api.month_summary.return_value = month_summary
    mock_api.invoices.return_value = invoices


# --------------------------------------------------------------------------
# Price sensors (unauthenticated)
# --------------------------------------------------------------------------

async def test_price_sensors_report_current_15min_slot(hass, mock_frank_energie_class, config_entry, freezer):
    """Sensors report values from the current 15-minute slot."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:07:00+01:00")

    electricity_today = [0.20] * 96
    electricity_today[40] = 0.42  # local 10:00-10:15 slot
    electricity_today[41] = 0.55  # local 10:15-10:30 slot
    gas_today = [1.10] * 96
    gas_today[40] = 1.75
    gas_today[41] = 1.60

    install_public_prices(mock_frank_energie_class, electricity_today, gas_today)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert state_for_key(hass, config_entry, "elec_markup").state == "0.42"
    assert state_for_key(hass, config_entry, "gas_markup").state == "1.75"

    # Advance to the next 15-minute slot and fire the entity's own scheduled update.
    freezer.move_to("2026-01-15 10:15:01+01:00")
    async_fire_time_changed(hass, dt_util.utcnow(), fire_all=True)
    await hass.async_block_till_done()

    assert state_for_key(hass, config_entry, "elec_markup").state == "0.55"
    assert state_for_key(hass, config_entry, "gas_markup").state == "1.6"


async def test_price_sensor_market_and_tax_breakdown(hass, mock_frank_energie_class, config_entry, freezer):
    """Market price / tax / sourcing markup sub-sensors report their own components."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    install_public_prices(mock_frank_energie_class, [0.2] * 96, [1.0] * 96)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # total = 0.7p (market) + 0.05p (tax) + 0.1p (markup) + 0.15p (energy tax), p=0.2
    market_price = float(state_for_key(hass, config_entry, "elec_market").state)
    price_with_tax = float(state_for_key(hass, config_entry, "elec_tax").state)
    assert state_for_key(hass, config_entry, "elec_markup").state == "0.2"
    assert market_price == pytest.approx(0.14)
    assert price_with_tax == pytest.approx(0.15)

    await enable_all_sensors(hass, config_entry)
    vat_price = float(state_for_key(hass, config_entry, "elec_tax_vat").state)
    sourcing_markup = float(state_for_key(hass, config_entry, "elec_sourcing").state)
    tax_only = float(state_for_key(hass, config_entry, "elec_tax_only").state)
    assert vat_price == pytest.approx(0.01)
    assert sourcing_markup == pytest.approx(0.02)
    assert tax_only == pytest.approx(0.03)


async def test_min_max_avg_sensors_today(hass, mock_frank_energie_class, config_entry, freezer):
    """Min/max/avg sensors reflect today's price data."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    electricity_prices = price_generator(0.25, 0.05, count=96)
    gas_prices = [1.75] * 48 + [1.23] * 48
    install_public_prices(mock_frank_energie_class, electricity_prices, gas_prices)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    elec_min = float(state_for_key(hass, config_entry, "elec_min").state)
    elec_max = float(state_for_key(hass, config_entry, "elec_max").state)
    elec_avg = float(state_for_key(hass, config_entry, "elec_avg").state)
    gas_min = float(state_for_key(hass, config_entry, "gas_min").state)
    gas_max = float(state_for_key(hass, config_entry, "gas_max").state)

    assert elec_min == pytest.approx(min(electricity_prices))
    assert elec_max == pytest.approx(max(electricity_prices))
    assert elec_avg == pytest.approx(sum(electricity_prices) / len(electricity_prices))
    assert gas_min == pytest.approx(1.23)
    assert gas_max == pytest.approx(1.75)


async def test_unauthenticated_entry_has_no_cost_or_invoice_sensors(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """No cost/invoice sensors should be created for an unauthenticated entry."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")
    install_public_prices(mock_frank_energie_class, [0.2] * 96, [1.0] * 96)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert entity_id_for_key(hass, config_entry, "actual_costs_until_last_meter_reading_date") is None
    assert entity_id_for_key(hass, config_entry, "invoice_previous_period") is None
    assert entity_id_for_key(hass, config_entry, "invoice_current_period") is None
    assert entity_id_for_key(hass, config_entry, "invoice_upcoming_period") is None


# --------------------------------------------------------------------------
# Invoice / cost sensors (authenticated)
# --------------------------------------------------------------------------

async def test_invoice_sensors_report_values(hass, mock_frank_energie_class, authenticated_config_entry, freezer):
    """Invoice sensors report TotalAmount and attributes from Invoices data."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    previous = make_invoice(120.5, datetime(2023, 12, 1, tzinfo=timezone.utc), "December 2023")
    current = make_invoice(80.0, datetime(2024, 1, 1, tzinfo=timezone.utc), "January 2024")
    upcoming = make_invoice(95.25, datetime(2024, 2, 1, tzinfo=timezone.utc), "February 2024")
    invoices = Invoices(
        all_periods_invoices=[previous, current, upcoming],
        previous_period_invoice=previous,
        current_period_invoice=current,
        upcoming_period_invoice=upcoming,
    )
    setup_authenticated_api(mock_frank_energie_class, invoices, month_summary=make_month_summary())

    assert await hass.config_entries.async_setup(authenticated_config_entry.entry_id)
    await hass.async_block_till_done()

    previous_state = state_for_key(hass, authenticated_config_entry, "invoice_previous_period")
    assert previous_state.state == "120.5"
    assert previous_state.attributes["Description"] == "December 2023"

    current_state = state_for_key(hass, authenticated_config_entry, "invoice_current_period")
    assert current_state.state == "80.0"

    upcoming_state = state_for_key(hass, authenticated_config_entry, "invoice_upcoming_period")
    assert upcoming_state.state == "95.25"

    actual_costs_state = state_for_key(hass, authenticated_config_entry, "actual_costs_until_last_meter_reading_date")
    assert actual_costs_state.state == "10.0"


async def test_invoice_sensor_missing_invoice_is_unavailable(
    hass, mock_frank_energie_class, authenticated_config_entry, freezer
):
    """A missing (None) invoice for a period should leave that sensor unavailable."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    invoices = Invoices(
        all_periods_invoices=[],
        previous_period_invoice=None,
        current_period_invoice=None,
        upcoming_period_invoice=None,
    )
    setup_authenticated_api(mock_frank_energie_class, invoices, month_summary=make_month_summary())

    assert await hass.config_entries.async_setup(authenticated_config_entry.entry_id)
    await hass.async_block_till_done()

    state = state_for_key(hass, authenticated_config_entry, "invoice_previous_period")
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


# --------------------------------------------------------------------------
# unique_id format
# --------------------------------------------------------------------------

async def test_unique_id_format(hass, mock_frank_energie_class, config_entry, freezer):
    """unique_id should be f'{entry.unique_id}.{key}'."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")
    install_public_prices(mock_frank_energie_class, [0.2] * 96, [1.0] * 96)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = entity_id_for_key(hass, config_entry, "elec_markup")
    assert entity_id is not None
    entry = er.async_get(hass).async_get(entity_id)
    assert entry.unique_id == f"{config_entry.unique_id}.elec_markup"


# --------------------------------------------------------------------------
# Edge case: missing month summary while authenticated
# --------------------------------------------------------------------------

async def test_month_summary_none_prevents_cost_sensors_from_being_added(
    hass, mock_frank_energie_class, authenticated_config_entry, freezer
):
    """month_summary() can legitimately return None (per its own type hint).

    SUSPECTED PRODUCTION BUG: FrankEnergieSensor.async_update() only catches
    (TypeError, IndexError, ValueError) around value_fn(), but the
    'actual_costs_until_last_meter_reading_date' / 'expected_costs_*' value_fn
    lambdas do `data[DATA_MONTH_SUMMARY].actualCostsUntilLastMeterReadingDate`,
    which raises AttributeError when DATA_MONTH_SUMMARY is None. Home
    Assistant's entity platform catches that during the initial
    update-before-add and logs "Error on device update!", but as a result the
    entity is never added to hass at all (not even as STATE_UNAVAILABLE) -
    the cost sensors silently disappear whenever month_summary() legitimately
    returns None (e.g. a brand new account with no meter reading yet). This
    test documents that behaviour rather than fixing the production code.
    """
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    invoices = Invoices.empty()
    setup_authenticated_api(mock_frank_energie_class, invoices, month_summary=None)

    assert await hass.config_entries.async_setup(authenticated_config_entry.entry_id)
    await hass.async_block_till_done()

    # Documenting current (buggy) behaviour: the entity never gets added.
    assert entity_id_for_key(hass, authenticated_config_entry, "actual_costs_until_last_meter_reading_date") is None
