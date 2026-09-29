"""Tests for Frank Energie sensors."""
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from python_frank_energie.models import ContractPriceResolutionState, Invoice, Invoices

from custom_components.frank_energie import const, sensor
from tests.utils import (
    build_market_prices,
    build_market_prices_from_local_midnight,
    build_price_data,
    make_me,
    make_month_summary,
    price_generator,
)

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

    # has_entity_name + translation_key: the friendly name combines the
    # device name and the translated entity name.
    friendly_name = state_for_key(hass, config_entry, "elec_markup").attributes["friendly_name"]
    assert friendly_name == "Frank Energie - Prices Current electricity price (All-in)"

    # Advance to the next 15-minute boundary and fire the entity's scheduled update.
    freezer.move_to("2026-01-15 10:15:00+01:00")
    async_fire_time_changed(hass, dt_util.utcnow())
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
    assert entity_id_for_key(hass, config_entry, "price_resolution") is None


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


@pytest.mark.parametrize(
    "key, has_last_reset, has_state_class",
    [("costs_this_year", True, True), ("costs_previous_year", False, False)],
    ids=["this_year", "previous_year"],
)
async def test_yearly_cost_sensors_report_totals_and_invoices_attribute(
    hass, mock_frank_energie_class, authenticated_config_entry, freezer, key, has_last_reset, has_state_class
):
    """costs_this_year/costs_previous_year report the matching Amsterdam year's total and invoices."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    this_year_invoice = make_invoice(80.0, datetime(2026, 1, 1, tzinfo=timezone.utc), "January 2026")
    previous_year_invoice = make_invoice(70.5, datetime(2025, 12, 1, tzinfo=timezone.utc), "December 2025")
    other_year_invoice = make_invoice(60.0, datetime(2024, 6, 1, tzinfo=timezone.utc), "June 2024")
    invoices = Invoices(all_periods_invoices=[this_year_invoice, previous_year_invoice, other_year_invoice])
    setup_authenticated_api(mock_frank_energie_class, invoices, month_summary=make_month_summary())

    assert await hass.config_entries.async_setup(authenticated_config_entry.entry_id)
    await hass.async_block_till_done()

    state = state_for_key(hass, authenticated_config_entry, key)
    expected_invoice = this_year_invoice if key == "costs_this_year" else previous_year_invoice
    assert float(state.state) == pytest.approx(expected_invoice.TotalAmount)
    invoice_attrs = state.attributes["invoices"]
    assert len(invoice_attrs) == 1
    assert invoice_attrs[0] == {
        "start_date": expected_invoice.StartDate.date().isoformat(),
        "description": expected_invoice.PeriodDescription,
        "total_amount": expected_invoice.TotalAmount,
    }

    assert (state.attributes.get("state_class") is not None) == has_state_class


async def test_yearly_cost_sensors_use_amsterdam_year_not_utc_year(
    hass, mock_frank_energie_class, authenticated_config_entry, freezer
):
    """At 00:30 Amsterdam time on 1 Jan (still 31 Dec UTC), the yearly sensors already use the new year."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2025-12-31 23:30:00+00:00")  # 2026-01-01 00:30 Europe/Amsterdam

    new_year_invoice = make_invoice(42.0, datetime(2026, 1, 1, tzinfo=timezone.utc), "January 2026")
    old_year_invoice = make_invoice(99.0, datetime(2025, 6, 1, tzinfo=timezone.utc), "June 2025")
    invoices = Invoices(all_periods_invoices=[new_year_invoice, old_year_invoice])
    setup_authenticated_api(mock_frank_energie_class, invoices, month_summary=make_month_summary())

    assert await hass.config_entries.async_setup(authenticated_config_entry.entry_id)
    await hass.async_block_till_done()

    this_year_state = state_for_key(hass, authenticated_config_entry, "costs_this_year")
    assert float(this_year_state.state) == pytest.approx(42.0)
    previous_year_state = state_for_key(hass, authenticated_config_entry, "costs_previous_year")
    assert float(previous_year_state.state) == pytest.approx(99.0)


async def test_yearly_cost_sensors_unavailable_when_invoices_is_none(
    hass, mock_frank_energie_class, authenticated_config_entry, freezer
):
    """costs_this_year/costs_previous_year are unavailable when invoices data is None."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")
    mock_frank_energie_class.is_authenticated = True
    mock_frank_energie_class.user_country.return_value = make_me("NL")
    mock_frank_energie_class.user_prices.return_value = build_market_prices(
        local_midnight(), [0.2] * 96, [1.0] * 96, resolution_minutes=15
    )
    mock_frank_energie_class.month_summary.return_value = None
    mock_frank_energie_class.invoices.return_value = None

    assert await hass.config_entries.async_setup(authenticated_config_entry.entry_id)
    await hass.async_block_till_done()

    assert state_for_key(hass, authenticated_config_entry, "costs_this_year").state == STATE_UNAVAILABLE
    assert state_for_key(hass, authenticated_config_entry, "costs_previous_year").state == STATE_UNAVAILABLE


async def test_price_resolution_sensor_reports_state_and_attributes(
    hass, mock_frank_energie_class, authenticated_config_entry, freezer
):
    """price_resolution reports the active option and its attributes, from ContractCoordinator."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")
    setup_authenticated_api(mock_frank_energie_class, Invoices.empty(), month_summary=make_month_summary())
    mock_frank_energie_class.user.return_value = MagicMock(
        connections=[MagicMock(segment="ELECTRICITY", connectionId="elec-conn")]
    )
    mock_frank_energie_class.contract_price_resolution_state.return_value = ContractPriceResolutionState(
        active_option="PT60M",
        available_options=["PT15M", "PT60M"],
        change_request_effective_date=None,
        is_change_request_possible=True,
        upcoming_change=None,
        upcoming_change_effective_date=None,
    )

    assert await hass.config_entries.async_setup(authenticated_config_entry.entry_id)
    await hass.async_block_till_done()

    state = state_for_key(hass, authenticated_config_entry, "price_resolution")
    assert state.state == "PT60M"
    assert state.attributes["available_options"] == ["PT15M", "PT60M"]
    assert state.attributes["is_change_request_possible"] is True
    assert state.attributes["upcoming_change"] is None


async def test_price_resolution_sensor_state_is_none_for_an_unknown_active_option(
    hass, mock_frank_energie_class, authenticated_config_entry, freezer
):
    """An active_option outside PT15M/PT60M (e.g. an API extension) reports state None, not a raw value."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")
    setup_authenticated_api(mock_frank_energie_class, Invoices.empty(), month_summary=make_month_summary())
    mock_frank_energie_class.user.return_value = MagicMock(
        connections=[MagicMock(segment="ELECTRICITY", connectionId="elec-conn")]
    )
    mock_frank_energie_class.contract_price_resolution_state.return_value = ContractPriceResolutionState(
        active_option="PT30M",
        available_options=["PT15M", "PT60M"],
        change_request_effective_date=None,
        is_change_request_possible=True,
        upcoming_change=None,
        upcoming_change_effective_date=None,
    )

    assert await hass.config_entries.async_setup(authenticated_config_entry.entry_id)
    await hass.async_block_till_done()

    state = state_for_key(hass, authenticated_config_entry, "price_resolution")
    assert state.state == STATE_UNKNOWN


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
    assert entry.unique_id == "frank_energie.elec_markup"


# --------------------------------------------------------------------------
# Edge case: missing month summary while authenticated
# --------------------------------------------------------------------------

async def test_month_summary_none_leaves_cost_sensors_unavailable(
    hass, mock_frank_energie_class, authenticated_config_entry, freezer
):
    """month_summary() can legitimately return None (per its own type hint).

    When that happens, the cost sensor value_fn lambdas explicitly return None
    (guarding on `data[DATA_MONTH_SUMMARY] is not None`) so the entities still
    get added to hass, just with a native value of None (i.e. state
    unavailable), instead of silently disappearing or raising.
    """
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    invoices = Invoices.empty()
    setup_authenticated_api(mock_frank_energie_class, invoices, month_summary=None)

    assert await hass.config_entries.async_setup(authenticated_config_entry.entry_id)
    await hass.async_block_till_done()

    for key in (
        "actual_costs_until_last_meter_reading_date",
        "expected_costs_until_last_meter_reading_date",
        "expected_costs_this_month",
    ):
        state = state_for_key(hass, authenticated_config_entry, key)
        assert state is not None, f"expected an entity for key={key}"
        assert state.state == STATE_UNAVAILABLE


async def test_unload_entry_cancels_update_timers(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """Unloading the config entry must cancel the sensors' quarter-hourly update timers."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")
    install_public_prices(mock_frank_energie_class, [0.2] * 96, [1.0] * 96)

    unsubscribers = []

    def fake_track_utc_time_change(*_args, **_kwargs):
        unsub = MagicMock(name="unsub")
        unsubscribers.append(unsub)
        return unsub

    with patch.object(sensor.event, "async_track_utc_time_change", side_effect=fake_track_utc_time_change):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    # One timer per legacy (declarative SENSOR_TYPES) sensor that was actually added
    # (disabled-by-default sensors get none), plus the single shared quarter-hour
    # timer PriceAnalysisCoordinator itself registers (see __init__.py), plus the
    # tomorrow_prices_available binary sensor's own quarter-hour timer. The
    # price-analysis sensors/binary sensors don't register their own per-entity
    # timer: they read PriceAnalysisCoordinator's cached, already
    # quarter-hourly-refreshed result instead.
    legacy_keys = [description.key for description in sensor.SENSOR_TYPES if not description.authenticated]
    legacy_added = [key for key in legacy_keys if state_for_key(hass, config_entry, key) is not None]
    assert unsubscribers
    assert len(unsubscribers) == len(legacy_added) + 2
    assert all(unsub.call_count == 0 for unsub in unsubscribers)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert all(unsub.call_count == 1 for unsub in unsubscribers)


# --------------------------------------------------------------------------
# _tz_name: PriceData.asdict(timezone=...) needs a string name, not a tzinfo
# object; datetime.timezone.utc (unlike ZoneInfo) has no `.key`.
# --------------------------------------------------------------------------


def test_tz_name_returns_key_for_zoneinfo_and_falls_back_to_utc_for_datetime_timezone_utc():
    """A ZoneInfo returns its `.key`; datetime.timezone.utc (no `.key` attribute) falls back to "UTC", not a crash."""
    from zoneinfo import ZoneInfo

    assert sensor._tz_name(ZoneInfo("Europe/Amsterdam")) == "Europe/Amsterdam"
    assert sensor._tz_name(dt_util.UTC) == "UTC"


async def test_prices_attribute_does_not_crash_with_home_assistant_option_and_utc_default_timezone(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """Regression test: prices_timezone="home_assistant" must not crash when the default time zone is plain UTC.

    Home Assistant's own DEFAULT_TIME_ZONE starts out as the
    datetime.timezone.utc singleton (before any async_set_time_zone() call),
    which has no `.key` attribute, unlike a ZoneInfo instance.
    """
    freezer.move_to("2026-01-15 10:00:00+00:00")
    dt_util.set_default_time_zone(dt_util.UTC)
    hass.config_entries.async_update_entry(
        config_entry, options={const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}
    )
    install_public_prices(mock_frank_energie_class, [0.2] * 96, [1.0] * 96, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    prices = state_for_key(hass, config_entry, "elec_markup").attributes["prices"]
    assert prices
    assert prices[0]["from"].utcoffset() == timedelta(0)


# --------------------------------------------------------------------------
# Recorder exclusion / error handling (unit tests, no hass setup needed)
# --------------------------------------------------------------------------

def test_unrecorded_attributes_excludes_prices():
    """The "prices" attribute must be excluded from the recorder (it can exceed the 16 KB limit)."""
    assert "prices" in sensor.FrankEnergieSensor._unrecorded_attributes


def test_no_data_errors_excludes_attribute_error():
    """AttributeError must not be swallowed as a generic 'no data' error.

    A renamed/removed library field should surface as a real error instead of
    silently showing the entity as unavailable.
    """
    assert AttributeError not in sensor._NO_DATA_ERRORS


async def test_attribute_error_from_value_fn_is_not_swallowed(hass, config_entry):
    """A value_fn raising AttributeError must propagate out of _compute_native_value.

    Uses data whose value_fn genuinely raises AttributeError (accessing an
    attribute on a None value), not a KeyError from a missing dict key, so
    this test actually exercises the AttributeError code path instead of
    passing vacuously.
    """
    coordinator = MagicMock()
    coordinator.data = {"x": None}
    description = sensor.FrankEnergieEntityDescription(
        key="broken",
        value_fn=lambda data: data["x"].missing_attr,
    )
    entity = sensor.FrankEnergieSensor(coordinator, description, config_entry)

    with pytest.raises(AttributeError):
        entity._compute_native_value()


# --------------------------------------------------------------------------
# Missing invoices while authenticated
# --------------------------------------------------------------------------

async def test_invoices_none_leaves_invoice_sensors_unavailable_with_empty_attrs(
    hass, mock_frank_energie_class, authenticated_config_entry, freezer
):
    """DATA_INVOICES can legitimately be None; invoice sensors must be unavailable with no invoice attrs."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")
    setup_authenticated_api(mock_frank_energie_class, invoices=None, month_summary=make_month_summary())

    assert await hass.config_entries.async_setup(authenticated_config_entry.entry_id)
    await hass.async_block_till_done()

    for key in ("invoice_previous_period", "invoice_current_period", "invoice_upcoming_period"):
        state = state_for_key(hass, authenticated_config_entry, key)
        assert state is not None, f"expected an entity for key={key}"
        assert state.state == STATE_UNAVAILABLE
        assert "Start date" not in state.attributes
        assert "Description" not in state.attributes


# --------------------------------------------------------------------------
# Immediate coordinator-refresh updates
# --------------------------------------------------------------------------

async def test_coordinator_refresh_updates_state_without_quarter_hour_tick(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """A coordinator refresh with new data updates sensor state immediately, without a scheduled tick."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")
    install_public_prices(mock_frank_energie_class, [0.2] * 96, [1.0] * 96)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert state_for_key(hass, config_entry, "elec_markup").state == "0.2"

    install_public_prices(mock_frank_energie_class, [0.77] * 96, [1.0] * 96)

    coordinator = config_entry.runtime_data.coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert state_for_key(hass, config_entry, "elec_markup").state == "0.77"


# --------------------------------------------------------------------------
# DST: 2026-10-25 "fall back" day (25 hours = 100 PT15M slots)
# --------------------------------------------------------------------------

async def test_dst_fall_back_day_min_max_avg_and_current_price(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """On the DST 'fall back' day, today_min/max/avg reflect all 100 slots and current price is correct.

    2026-10-25 is 25 hours long (100 PT15M slots) because clocks are set back
    an hour. Local 02:30-02:45 therefore occurs twice: once at UTC+2 (CEST,
    slot index 10) and once at UTC+1 (CET, slot index 14).
    """
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    # Set up before the ambiguous hour so later moves (to 02:30 CEST, then
    # 02:30 CET) are always forward in absolute time; HA's scheduled time
    # trackers only fire for moments after the time they were registered at.
    freezer.move_to("2026-10-25 00:00:00+02:00")

    local_midnight = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
    electricity_prices = [0.20] * 100
    electricity_prices[10] = 0.41  # first occurrence of local 02:30-02:45 (CEST, UTC+2)
    electricity_prices[14] = 0.63  # second occurrence of local 02:30-02:45 (CET, UTC+1)
    gas_prices = [1.10] * 100

    today = build_market_prices_from_local_midnight(local_midnight, electricity_prices, gas_prices)
    tomorrow_midnight = local_midnight + timedelta(days=1)
    tomorrow = build_market_prices_from_local_midnight(tomorrow_midnight, [0.3] * 96, [1.2] * 96)

    async def prices_side_effect(start_date, resolution="PT15M"):
        if start_date == local_midnight.date():
            return today
        return tomorrow

    mock_frank_energie_class.prices.side_effect = prices_side_effect

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    elec_min = float(state_for_key(hass, config_entry, "elec_min").state)
    elec_max = float(state_for_key(hass, config_entry, "elec_max").state)
    elec_avg = float(state_for_key(hass, config_entry, "elec_avg").state)
    assert elec_min == pytest.approx(min(electricity_prices))
    assert elec_max == pytest.approx(max(electricity_prices))
    assert elec_avg == pytest.approx(sum(electricity_prices) / len(electricity_prices))

    # First occurrence of local 02:30 (CEST, UTC+2) -> slot index 10.
    freezer.move_to("2026-10-25 02:30:00+02:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert state_for_key(hass, config_entry, "elec_markup").state == "0.41"

    # Second occurrence of local 02:30 (CET, UTC+1, after the clock is set back) -> slot index 14.
    freezer.move_to("2026-10-25 02:30:00+01:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert state_for_key(hass, config_entry, "elec_markup").state == "0.63"


# --------------------------------------------------------------------------
# Midnight rollover
# --------------------------------------------------------------------------

async def test_midnight_rollover_shows_tomorrows_first_slot(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """At the moment of midnight rollover, the sensor state should switch to tomorrow's first slot."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 23:59:59+01:00")

    today_electricity = [0.20] * 96
    tomorrow_electricity = [0.55] * 96
    install_public_prices(mock_frank_energie_class, today_electricity, [1.0] * 96, tomorrow_electricity, [1.2] * 96)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert state_for_key(hass, config_entry, "elec_markup").state == "0.2"

    freezer.move_to("2026-01-16 00:00:00+01:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert state_for_key(hass, config_entry, "elec_markup").state == "0.55"


# --------------------------------------------------------------------------
# Regression: unavailable (not crashing/stale) when no price slot matches
# (see commit 2b938ed, "Show sensors as unavailable when no price slot
# matches").
# --------------------------------------------------------------------------

async def test_empty_gas_price_data_leaves_gas_sensors_unavailable_without_errors(
    hass, mock_frank_energie_class, config_entry, freezer, caplog
):
    """Empty gas PriceData (electricity normal) must not crash sensor updates.

    Every gas price sensor (current all-in/market/tax and the
    disabled-by-default ones once enabled, plus gas_min/gas_max) should be
    unavailable, with no error logged by the sensor platform, and
    gas_min/gas_max should render with no "from_time" attribute.
    """
    caplog.set_level(logging.DEBUG)
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    # Gas is empty both today and tomorrow; electricity is normal.
    install_public_prices(mock_frank_energie_class, [0.2] * 96, [], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await enable_all_sensors(hass, config_entry)

    gas_keys = (
        "gas_markup",
        "gas_market",
        "gas_tax",
        "gas_tax_vat",
        "gas_sourcing",
        "gas_tax_only",
        "gas_min",
        "gas_max",
    )
    for key in gas_keys:
        state = state_for_key(hass, config_entry, key)
        assert state is not None, f"expected an entity for key={key}"
        assert state.state == STATE_UNAVAILABLE, f"{key} expected unavailable, got {state.state!r}"

    for key in ("gas_min", "gas_max"):
        state = state_for_key(hass, config_entry, key)
        assert "from_time" not in state.attributes

    # Electricity is unaffected by the empty gas data.
    assert state_for_key(hass, config_entry, "elec_markup").state == "0.2"

    errors = [
        record
        for record in caplog.records
        if record.name.startswith("custom_components.frank_energie") and record.levelno >= logging.ERROR
    ]
    assert not errors, f"unexpected error log(s) from the sensor platform: {errors}"


async def test_no_current_slot_after_midnight_shows_unavailable_not_stale(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """With no tomorrow price data, current-price sensors go unavailable at midnight, not stale.

    Prices are only available for today (public fallback for tomorrow is
    empty). Once the clock crosses local midnight, there is no slot left that
    matches "now", so the current-price sensors must become unavailable
    instead of continuing to show the last (now stale) price. today_min/
    today_max must also render without raising, even though there is no
    longer any "today" data either.
    """
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 23:59:59+01:00")

    install_public_prices(
        mock_frank_energie_class,
        [0.20] * 96,
        [1.00] * 96,
        tomorrow_electricity=[],
        tomorrow_gas=[],
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert state_for_key(hass, config_entry, "elec_markup").state == "0.2"
    assert state_for_key(hass, config_entry, "gas_markup").state == "1.0"

    freezer.move_to("2026-01-16 00:00:00+01:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert state_for_key(hass, config_entry, "elec_markup").state == STATE_UNAVAILABLE
    assert state_for_key(hass, config_entry, "gas_markup").state == STATE_UNAVAILABLE

    # today_min/today_max must render (no exception), even with no data left.
    assert state_for_key(hass, config_entry, "elec_min").state == STATE_UNAVAILABLE
    assert state_for_key(hass, config_entry, "elec_max").state == STATE_UNAVAILABLE


# --------------------------------------------------------------------------
# New sensors: elec_next, elec_tomorrow_avg/min/max, elec_upcoming_min/max,
# gas_tomorrow_avg (see commit bad4b3a, "Add upcoming and tomorrow price
# sensors").
# --------------------------------------------------------------------------

NEW_SENSOR_KEYS = (
    "elec_next",
    "elec_tomorrow_avg",
    "elec_tomorrow_min",
    "elec_tomorrow_max",
    "elec_upcoming_min",
    "elec_upcoming_max",
    "gas_tomorrow_avg",
)


def test_new_price_sensors_are_enabled_by_default():
    """All 7 new sensors must be enabled by default (no opt-in required)."""
    descriptions = {desc.key: desc for desc in sensor.SENSOR_TYPES}
    for key in NEW_SENSOR_KEYS:
        assert key in descriptions, f"missing sensor description for key={key}"
        assert descriptions[key].entity_registry_enabled_default is not False, (
            f"{key} must be enabled by default"
        )


async def test_new_price_sensors_with_today_and_tomorrow_data(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """With today and tomorrow data, the 7 new sensors report the right values and from_time."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")  # local slot index 40 (10:00-10:15) is "now"

    electricity_today = [0.20] * 96
    electricity_today[50] = 0.05  # a later-today slot: the lowest "upcoming" price
    tomorrow_midnight = local_midnight() + timedelta(days=1)

    electricity_tomorrow = price_generator(0.30, 0.02, count=96)
    electricity_tomorrow[5] = 9.99  # tomorrow's highest price, also the highest "upcoming" price
    gas_tomorrow = [1.75] * 48 + [1.23] * 48

    install_public_prices(
        mock_frank_energie_class,
        electricity_today,
        [1.0] * 96,
        tomorrow_electricity=electricity_tomorrow,
        tomorrow_gas=gas_tomorrow,
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # elec_next: the slot right after "now" (10:15-10:30, index 41).
    next_state = state_for_key(hass, config_entry, "elec_next")
    assert float(next_state.state) == pytest.approx(electricity_today[41])
    expected_next_from = local_midnight() + timedelta(minutes=15 * 41)
    assert next_state.attributes["from_time"] == expected_next_from

    # elec_tomorrow_avg / gas_tomorrow_avg.
    tomorrow_avg_state = state_for_key(hass, config_entry, "elec_tomorrow_avg")
    assert float(tomorrow_avg_state.state) == pytest.approx(
        sum(electricity_tomorrow) / len(electricity_tomorrow)
    )
    gas_tomorrow_avg_state = state_for_key(hass, config_entry, "gas_tomorrow_avg")
    assert float(gas_tomorrow_avg_state.state) == pytest.approx(sum(gas_tomorrow) / len(gas_tomorrow))

    # elec_tomorrow_min / elec_tomorrow_max.
    tomorrow_min_state = state_for_key(hass, config_entry, "elec_tomorrow_min")
    assert float(tomorrow_min_state.state) == pytest.approx(min(electricity_tomorrow))
    tomorrow_max_state = state_for_key(hass, config_entry, "elec_tomorrow_max")
    assert float(tomorrow_max_state.state) == pytest.approx(max(electricity_tomorrow))
    max_index = electricity_tomorrow.index(max(electricity_tomorrow))
    assert tomorrow_max_state.attributes["from_time"] == tomorrow_midnight + timedelta(minutes=15 * max_index)

    # elec_upcoming_min/max span both the rest of today and all of tomorrow.
    upcoming_min_state = state_for_key(hass, config_entry, "elec_upcoming_min")
    assert float(upcoming_min_state.state) == pytest.approx(0.05)
    assert upcoming_min_state.attributes["from_time"] == local_midnight() + timedelta(minutes=15 * 50)

    upcoming_max_state = state_for_key(hass, config_entry, "elec_upcoming_max")
    assert float(upcoming_max_state.state) == pytest.approx(9.99)
    assert upcoming_max_state.attributes["from_time"] == tomorrow_midnight + timedelta(minutes=15 * 5)


@pytest.mark.parametrize(
    "tomorrow_electricity, expected_is_on",
    [([0.3] * 96, True), ([], False)],
    ids=["tomorrow_present", "tomorrow_absent"],
)
async def test_tomorrow_prices_available_binary_sensor(
    hass, mock_frank_energie_class, config_entry, freezer, tomorrow_electricity, expected_is_on
):
    """The tomorrow_prices_available binary sensor is on iff tomorrow's electricity prices are present."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    install_public_prices(
        mock_frank_energie_class, [0.2] * 96, [1.0] * 96, tomorrow_electricity=tomorrow_electricity
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor", const.DOMAIN, f"{config_entry.unique_id}.tomorrow_prices_available"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state.state == ("on" if expected_is_on else "off")
    assert ("date" in state.attributes) == expected_is_on


async def test_tomorrow_prices_available_binary_sensor_turns_off_after_midnight_without_a_poll(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """After midnight, is_on flips off on the next quarter-hour timer tick, without a new API call."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 23:59:00+01:00")

    install_public_prices(mock_frank_energie_class, [0.2] * 96, [1.0] * 96, tomorrow_electricity=[0.3] * 96)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor", const.DOMAIN, f"{config_entry.unique_id}.tomorrow_prices_available"
    )
    assert hass.states.get(entity_id).state == "on"
    assert hass.states.get(entity_id).attributes["date"] == "2026-01-16"

    prices_call_count = mock_frank_energie_class.prices.call_count
    freezer.move_to("2026-01-16 00:00:00+01:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "off"
    assert "date" not in hass.states.get(entity_id).attributes
    assert mock_frank_energie_class.prices.call_count == prices_call_count


def test_next_price_returns_none_for_empty_price_data():
    """No slots at all -> None (so elec_next's value_fn reports None, not a crash)."""
    from python_frank_energie.models import PriceData

    price_data = PriceData([], energy_type="electricity")
    assert sensor._next_price(price_data) is None


@pytest.mark.parametrize(
    "resolution_minutes, start_hour, start_minute, expected_next_from",
    [
        # 60-minute slots: must return the next hour, not the current (up to
        # 45-minute-stale) hour. Regression test for elec_next using
        # PriceData.next_quarter_hour (now + 15 minutes), which pointed at
        # the current hour's slot for the first 45 minutes of every hour.
        (60, 9, 0, datetime(2026, 1, 15, 11, 0, tzinfo=timezone.utc)),
        # 15-minute slots: the next quarter-hour slot, matching old behaviour.
        (15, 9, 45, datetime(2026, 1, 15, 10, 15, tzinfo=timezone.utc)),
    ],
    ids=["60_minute_slots", "15_minute_slots"],
)
def test_next_price_returns_the_next_slot_for_the_slot_resolution(
    freezer, resolution_minutes, start_hour, start_minute, expected_next_from
):
    """_next_price returns the slot right after "now", whatever the slots' own resolution."""
    freezer.move_to("2026-01-15 10:07:00+00:00")
    start = datetime(2026, 1, 15, start_hour, start_minute, tzinfo=timezone.utc)
    price_data = build_price_data(start, [0.10, 0.20, 0.30], "electricity", resolution_minutes=resolution_minutes)

    next_price = sensor._next_price(price_data)

    assert next_price is not None
    assert next_price.total == pytest.approx(0.30)
    assert next_price.date_from == expected_next_from


async def test_elec_next_sensor_uses_next_hour_with_60_minute_slots(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """Integration-level regression test: elec_next reports the next hour's price with 60-minute slots."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:07:00+01:00")  # 7 minutes into the 10:00-11:00 local slot

    today = local_midnight()
    electricity_today = [0.10] * 24
    electricity_today[10] = 0.20  # current hour (10:00-11:00)
    electricity_today[11] = 0.30  # next hour (11:00-12:00): expected elec_next value

    today_prices = build_market_prices(today, electricity_today, [1.0] * 24, resolution_minutes=60)
    tomorrow_prices = build_market_prices(
        today + timedelta(days=1), [0.3] * 24, [1.2] * 24, resolution_minutes=60
    )

    async def prices_side_effect(start_date, resolution="PT15M"):
        if start_date == dt_util.now().date():
            return today_prices
        return tomorrow_prices

    mock_frank_energie_class.prices.side_effect = prices_side_effect

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    next_state = state_for_key(hass, config_entry, "elec_next")
    assert float(next_state.state) == pytest.approx(0.30)
    assert next_state.attributes["from_time"] == today + timedelta(hours=11)


async def test_new_price_sensors_without_tomorrow_data(hass, mock_frank_energie_class, config_entry, freezer, caplog):
    """Without tomorrow data, tomorrow sensors are unavailable (no errors); next/upcoming still work from today."""
    caplog.set_level(logging.DEBUG)
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    electricity_today = [0.20] * 96
    electricity_today[41] = 0.42  # next slot after "now"
    electricity_today[80] = 0.01  # a later-today slot: the lowest upcoming price

    install_public_prices(
        mock_frank_energie_class,
        electricity_today,
        [1.0] * 96,
        tomorrow_electricity=[],
        tomorrow_gas=[],
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    for key in ("elec_tomorrow_avg", "elec_tomorrow_min", "elec_tomorrow_max", "gas_tomorrow_avg"):
        state = state_for_key(hass, config_entry, key)
        assert state is not None, f"expected an entity for key={key}"
        assert state.state == STATE_UNAVAILABLE, f"{key} expected unavailable, got {state.state!r}"

    next_state = state_for_key(hass, config_entry, "elec_next")
    assert float(next_state.state) == pytest.approx(0.42)

    upcoming_min_state = state_for_key(hass, config_entry, "elec_upcoming_min")
    assert float(upcoming_min_state.state) == pytest.approx(0.01)
    upcoming_max_state = state_for_key(hass, config_entry, "elec_upcoming_max")
    assert upcoming_max_state.state != STATE_UNAVAILABLE

    errors = [
        record
        for record in caplog.records
        if record.name.startswith("custom_components.frank_energie") and record.levelno >= logging.ERROR
    ]
    assert not errors, f"unexpected error log(s) from the sensor platform: {errors}"


# --------------------------------------------------------------------------
# prices_timezone option: "prices" attribute and from_time attribute notation
# (see commit d6a5dc3, "Add option for the time zone of price times").
# --------------------------------------------------------------------------

FROM_TIME_KEYS = (
    "elec_min",
    "elec_max",
    "gas_min",
    "gas_max",
    "elec_next",
    "elec_tomorrow_min",
    "elec_tomorrow_max",
    "elec_upcoming_min",
    "elec_upcoming_max",
)


@pytest.mark.parametrize(
    "options, freeze_time, expected_offset",
    [
        (None, "2026-01-15 10:00:00+01:00", timedelta(0)),
        ({const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}, "2026-01-15 10:00:00+01:00",
         timedelta(hours=1)),
        ({const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}, "2026-07-15 10:00:00+02:00",
         timedelta(hours=2)),
    ],
    ids=["utc_default", "home_assistant_winter", "home_assistant_summer"],
)
async def test_prices_attribute_offset_follows_prices_timezone_option(
    hass, mock_frank_energie_class, config_entry, freezer, options, freeze_time, expected_offset
):
    """The "prices" attribute's from/till utcoffset follows prices_timezone: UTC by default, else the HA tz offset.

    With "home_assistant" that means +01:00 in winter (CET) and +02:00 in
    summer (CEST) for Europe/Amsterdam.
    """
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to(freeze_time)
    if options is not None:
        hass.config_entries.async_update_entry(config_entry, options=options)
    install_public_prices(mock_frank_energie_class, [0.2] * 96, [1.0] * 96, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    prices = state_for_key(hass, config_entry, "elec_markup").attributes["prices"]
    assert prices
    for slot in prices:
        assert slot["from"].utcoffset() == expected_offset
        assert slot["till"].utcoffset() == expected_offset


async def test_changing_prices_timezone_via_options_flow_updates_prices_notation_without_restart(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """Changing prices_timezone via the options flow updates the "prices" notation after reload, same instants."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")
    install_public_prices(mock_frank_energie_class, [0.2] * 96, [1.0] * 96, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    utc_prices = state_for_key(hass, config_entry, "elec_markup").attributes["prices"]
    assert utc_prices
    assert all(slot["from"].utcoffset() == timedelta(0) for slot in utc_prices)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT,
            const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_STATISTICS],
        },
    )
    await hass.async_block_till_done()
    assert result2["type"] == "create_entry"
    assert config_entry.state is ConfigEntryState.LOADED

    ha_prices = state_for_key(hass, config_entry, "elec_markup").attributes["prices"]
    assert ha_prices
    assert all(slot["from"].utcoffset() == timedelta(hours=1) for slot in ha_prices)

    # Same underlying instants across both options, only the notation differs.
    assert [s["from"] for s in utc_prices] == [s["from"] for s in ha_prices]
    assert [s["till"] for s in utc_prices] == [s["till"] for s in ha_prices]


async def test_from_time_attributes_default_to_utc_then_follow_home_assistant_timezone_with_same_instant(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """from_time attributes have utcoffset 0 by default; with "home_assistant" they use the HA tz offset instead.

    Both notations represent the same instant.
    """
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")
    install_public_prices(
        mock_frank_energie_class, [0.2] * 96, [1.0] * 96, tomorrow_electricity=[0.3] * 96, tomorrow_gas=[1.2] * 96
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    utc_from_times = {}
    for key in FROM_TIME_KEYS:
        state = state_for_key(hass, config_entry, key)
        assert state is not None, f"expected an entity for key={key}"
        from_time = state.attributes["from_time"]
        assert from_time.utcoffset() == timedelta(0), f"{key}: expected utc offset 0, got {from_time.utcoffset()}"
        utc_from_times[key] = from_time

    hass.config_entries.async_update_entry(
        config_entry, options={const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}
    )
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    for key in FROM_TIME_KEYS:
        state = state_for_key(hass, config_entry, key)
        from_time = state.attributes["from_time"]
        assert from_time.utcoffset() == timedelta(hours=1), f"{key}: expected +01:00, got {from_time.utcoffset()}"
        assert from_time == utc_from_times[key], f"{key}: instant changed across prices_timezone options"


async def test_new_price_sensors_late_in_day_next_and_upcoming_unavailable(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """Late in the day, with only today's data, next/upcoming sensors become unavailable once no slots remain."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 23:50:00+01:00")  # inside the last slot (23:45-00:00)

    install_public_prices(
        mock_frank_energie_class,
        [0.20] * 96,
        [1.0] * 96,
        tomorrow_electricity=[],
        tomorrow_gas=[],
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    for key in ("elec_next", "elec_upcoming_min", "elec_upcoming_max"):
        state = state_for_key(hass, config_entry, key)
        assert state is not None, f"expected an entity for key={key}"
        assert state.state == STATE_UNAVAILABLE, f"{key} expected unavailable, got {state.state!r}"
