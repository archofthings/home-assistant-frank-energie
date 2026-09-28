"""Tests for the Frank Energie get_prices service."""
from datetime import datetime, timedelta

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.frank_energie import const
from custom_components.frank_energie.services import SERVICE_GET_PRICES
from tests.utils import build_market_prices, build_market_prices_from_local_midnight

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def local_midnight():
    """Today's local midnight, as an aware datetime, honoring hass's configured timezone."""
    return dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)


def install_prices(
    mock_api,
    today_electricity,
    today_gas,
    tomorrow_electricity=None,
    tomorrow_gas=None,
    resolution_minutes=60,
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


async def call_get_prices(hass, **data):
    """Call the get_prices service (blocking, with a response)."""
    return await hass.services.async_call(
        const.DOMAIN, SERVICE_GET_PRICES, data, blocking=True, return_response=True
    )


# --------------------------------------------------------------------------
# No start/end: all slots, value mapping, ISO local times and rounding
# --------------------------------------------------------------------------


async def test_get_prices_no_filter_returns_all_slots(hass, mock_frank_energie_class, config_entry, freezer):
    """Without start/end, all cached slots (today + tomorrow) are returned for both segments."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    install_prices(
        mock_frank_energie_class,
        [0.10, 0.20, 0.30, 0.40],
        [1.00, 1.10, 1.20, 1.30],
        tomorrow_electricity=[0.50, 0.60, 0.70, 0.80],
        tomorrow_gas=[1.40, 1.50, 1.60, 1.70],
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id)

    assert len(response["electricity"]) == 8
    assert len(response["gas"]) == 8


async def test_get_prices_item_keys_and_value_mapping(hass, mock_frank_energie_class, config_entry, freezer):
    """Each price item exposes the documented keys, mapped from the right Price fields, rounded to 5 decimals."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")
    # config_entry has no options, so prices_timezone defaults to "utc"; opt into
    # "home_assistant" explicitly to test the local (Europe/Amsterdam) notation here.
    hass.config_entries.async_update_entry(
        config_entry, options={const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}
    )

    # price_dicts() derives marketPrice/marketPriceTax/sourcingMarkupPrice/energyTaxPrice from
    # the input price and rounds each to 6 decimals; the service then rounds each field to 5.
    price = 0.123456
    install_prices(mock_frank_energie_class, [price], [1.0], tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id)

    assert len(response["electricity"]) == 1
    item = response["electricity"][0]

    assert set(item.keys()) == {
        "start",
        "end",
        "price",
        "market_price",
        "market_price_including_tax",
        "vat",
        "sourcing_markup",
        "energy_tax",
    }

    today = local_midnight()
    assert item["start"] == dt_util.as_local(today).isoformat()
    assert item["end"] == dt_util.as_local(today + timedelta(hours=1)).isoformat()

    market_price_field = round(0.7 * price, 6)
    market_price_tax_field = round(0.05 * price, 6)
    sourcing_markup_field = round(0.1 * price, 6)
    energy_tax_field = round(0.15 * price, 6)

    total_field = market_price_field + market_price_tax_field + sourcing_markup_field + energy_tax_field
    assert item["price"] == round(total_field, 5)
    assert item["market_price"] == round(market_price_field, 5)
    assert item["vat"] == round(market_price_tax_field, 5)
    assert item["sourcing_markup"] == round(sourcing_markup_field, 5)
    assert item["energy_tax"] == round(energy_tax_field, 5)
    assert item["market_price_including_tax"] == round(market_price_field + market_price_tax_field, 5)


async def test_get_prices_start_iso_time_has_utc_offset_by_default(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """With no prices_timezone option (legacy entry default), ISO start/end times end in "+00:00" (UTC)."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")  # CET, winter

    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id)

    assert response["electricity"][0]["start"].endswith("+00:00")
    assert response["electricity"][0]["end"].endswith("+00:00")


async def test_get_prices_start_iso_time_has_amsterdam_summer_offset_with_home_assistant_option(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """With the "home_assistant" option, ISO times use +02:00 in summer (Europe/Amsterdam, CEST)."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-07-15 10:00:00+02:00")  # CEST, summer: +02:00
    hass.config_entries.async_update_entry(
        config_entry, options={const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}
    )

    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id)

    assert response["electricity"][0]["start"].endswith("+02:00")
    assert response["electricity"][0]["end"].endswith("+02:00")


async def test_get_prices_start_local_iso_time_has_amsterdam_offset(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """ISO local times use the Europe/Amsterdam offset, not UTC."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")  # CET, winter: +01:00
    # config_entry has no options, so prices_timezone defaults to "utc"; opt into
    # "home_assistant" explicitly to test the local (Europe/Amsterdam) notation here.
    hass.config_entries.async_update_entry(
        config_entry, options={const.CONF_PRICES_TIMEZONE: const.PRICES_TIMEZONE_HOME_ASSISTANT}
    )

    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id)

    assert response["electricity"][0]["start"].endswith("+01:00")


# --------------------------------------------------------------------------
# start/end filter: overlap semantics
# --------------------------------------------------------------------------


async def test_get_prices_overlap_window_includes_partially_overlapping_slots(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """A start/end window that only partly overlaps a slot still includes that slot."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    install_prices(
        mock_frank_energie_class, [0.10, 0.20, 0.30, 0.40], [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[]
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    today = local_midnight()
    # Window [00:45, 01:15) partly overlaps slot 0 (00:00-01:00) and slot 1 (01:00-02:00),
    # neither of which is fully contained in the window.
    start = today + timedelta(minutes=45)
    end = today + timedelta(hours=1, minutes=15)

    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id, start=start, end=end)

    prices = [item["price"] for item in response["electricity"]]
    assert prices == pytest.approx([0.10, 0.20])


async def test_get_prices_start_only_includes_slots_ending_after_start(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """With only `start` set, slots ending at/before start are excluded, all later slots included."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    install_prices(
        mock_frank_energie_class, [0.10, 0.20, 0.30, 0.40], [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[]
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    today = local_midnight()
    start = today + timedelta(hours=1, minutes=30)  # inside slot 1 (01:00-02:00)

    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id, start=start)

    prices = [item["price"] for item in response["electricity"]]
    assert prices == pytest.approx([0.20, 0.30, 0.40])


async def test_get_prices_end_only_includes_slots_starting_before_end(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """With only `end` set, slots starting at/after end are excluded, all earlier slots included."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    install_prices(
        mock_frank_energie_class, [0.10, 0.20, 0.30, 0.40], [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[]
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    today = local_midnight()
    end = today + timedelta(hours=1, minutes=30)  # inside slot 1 (01:00-02:00)

    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id, end=end)

    prices = [item["price"] for item in response["electricity"]]
    assert prices == pytest.approx([0.10, 0.20])


async def test_get_prices_naive_datetime_interpreted_as_ha_local_time(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """A naive `start` datetime is interpreted in HA's configured local timezone, not UTC."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")  # CET = UTC+1

    install_prices(
        mock_frank_energie_class, [0.10, 0.20, 0.30, 0.40], [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[]
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Naive local time 01:30 (Europe/Amsterdam, CET = UTC+1) -> 00:30 UTC.
    naive_start = datetime(2026, 1, 15, 1, 30)
    assert naive_start.tzinfo is None

    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id, start=naive_start)

    prices = [item["price"] for item in response["electricity"]]
    assert prices == pytest.approx([0.20, 0.30, 0.40])


async def test_get_prices_naive_start_on_dst_fall_back_day(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """A naive `start` on the Europe/Amsterdam DST 'fall back' day (2026-10-25) uses the correct UTC offset.

    2026-10-25 is 25 hours long in local time (clocks are set back an hour at
    03:00 CEST). A naive 01:30 that day is unambiguous and still CEST
    (+02:00); if it were (mis)interpreted with a fixed +01:00 offset instead,
    the wrong slot would be excluded from the filtered result.
    """
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-10-25 00:00:00+02:00")

    local_midnight_dt = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
    electricity_prices = [float(i) for i in range(25)]  # 25 hourly slots on the 25-hour fall-back day
    gas_prices = [1.0] * 25

    today = build_market_prices_from_local_midnight(
        local_midnight_dt, electricity_prices, gas_prices, resolution_minutes=60
    )
    tomorrow = build_market_prices_from_local_midnight(
        local_midnight_dt + timedelta(days=1), [0.3] * 24, [1.2] * 24, resolution_minutes=60
    )

    async def prices_side_effect(start_date, resolution="PT15M"):
        if start_date == local_midnight_dt.date():
            return today
        return tomorrow

    mock_frank_energie_class.prices.side_effect = prices_side_effect

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Naive local 01:30 (unambiguous, still CEST/+02:00, before the 03:00->02:00 rollback).
    naive_start = datetime(2026, 10, 25, 1, 30)
    assert naive_start.tzinfo is None
    # Bound `end` to today's last slot, so tomorrow's (unrelated) slots don't need asserting on too.
    end = today.electricity.price_data[-1].date_till

    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id, start=naive_start, end=end)

    prices = [item["price"] for item in response["electricity"]]
    assert prices == pytest.approx(electricity_prices[1:])


# --------------------------------------------------------------------------
# coordinator.data is None (e.g. before the first successful refresh)
# --------------------------------------------------------------------------


async def test_get_prices_returns_empty_lists_when_coordinator_data_is_none(
    hass, mock_frank_energie_class, config_entry
):
    """When coordinator.data is None, get_prices returns empty electricity/gas lists rather than raising."""
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[const.DOMAIN][config_entry.entry_id][const.CONF_COORDINATOR]
    coordinator.data = None

    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id)

    assert response == {"electricity": [], "gas": []}


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


async def test_get_prices_unknown_entry_id_raises_entry_not_found(hass, mock_frank_energie_class, config_entry):
    """An unknown config_entry_id raises ServiceValidationError with translation_key entry_not_found."""
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as exc_info:
        await call_get_prices(hass, config_entry_id="does-not-exist")

    assert exc_info.value.translation_domain == const.DOMAIN
    assert exc_info.value.translation_key == "entry_not_found"
    assert exc_info.value.translation_placeholders == {"entry_id": "does-not-exist"}


async def test_get_prices_entry_of_another_domain_raises_entry_not_found(
    hass, mock_frank_energie_class, config_entry, enable_custom_integrations
):
    """A config entry that exists but belongs to another domain also raises entry_not_found."""
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    other_entry = MockConfigEntry(domain="other_domain", data={}, unique_id="other")
    other_entry.add_to_hass(hass)

    with pytest.raises(ServiceValidationError) as exc_info:
        await call_get_prices(hass, config_entry_id=other_entry.entry_id)

    assert exc_info.value.translation_key == "entry_not_found"


async def test_get_prices_unloaded_entry_raises_entry_not_loaded(hass, mock_frank_energie_class, config_entry):
    """A Frank Energie entry that exists but is not loaded raises entry_not_loaded."""
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as exc_info:
        await call_get_prices(hass, config_entry_id=config_entry.entry_id)

    assert exc_info.value.translation_key == "entry_not_loaded"
    assert exc_info.value.translation_placeholders == {"entry_id": config_entry.entry_id}


async def test_get_prices_start_after_end_raises_invalid_period(hass, mock_frank_energie_class, config_entry):
    """start > end raises ServiceValidationError with translation_key invalid_period."""
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    today = local_midnight()
    start = today + timedelta(hours=2)
    end = today + timedelta(hours=1)

    with pytest.raises(ServiceValidationError) as exc_info:
        await call_get_prices(hass, config_entry_id=config_entry.entry_id, start=start, end=end)

    assert exc_info.value.translation_domain == const.DOMAIN
    assert exc_info.value.translation_key == "invalid_period"


async def test_get_prices_start_equal_end_raises_invalid_period(hass, mock_frank_energie_class, config_entry):
    """start == end also raises ServiceValidationError with translation_key invalid_period (an empty period)."""
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    today = local_midnight()
    start = today + timedelta(hours=1)
    end = today + timedelta(hours=1)

    with pytest.raises(ServiceValidationError) as exc_info:
        await call_get_prices(hass, config_entry_id=config_entry.entry_id, start=start, end=end)

    assert exc_info.value.translation_domain == const.DOMAIN
    assert exc_info.value.translation_key == "invalid_period"


# --------------------------------------------------------------------------
# No API calls: the service only reads cached coordinator data
# --------------------------------------------------------------------------


async def test_get_prices_makes_no_additional_api_calls(hass, mock_frank_energie_class, config_entry, freezer):
    """Calling get_prices must not trigger any additional calls to the Frank Energie API."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    install_prices(
        mock_frank_energie_class,
        [0.2] * 4,
        [1.0] * 4,
        tomorrow_electricity=[0.3] * 4,
        tomorrow_gas=[1.2] * 4,
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    call_count_before = mock_frank_energie_class.prices.call_count

    await call_get_prices(hass, config_entry_id=config_entry.entry_id)
    await call_get_prices(hass, config_entry_id=config_entry.entry_id, start=local_midnight())

    assert mock_frank_energie_class.prices.call_count == call_count_before


# --------------------------------------------------------------------------
# Registration and availability across setup/unload/reload
# --------------------------------------------------------------------------


def _service_registered(hass) -> bool:
    return SERVICE_GET_PRICES in hass.services.async_services().get(const.DOMAIN, {})


async def test_get_prices_registered_after_setup_and_survives_unload_reload(
    hass, mock_frank_energie_class, config_entry, freezer
):
    """The service is registered once the component is set up, and keeps working across unload/reload."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-01-15 10:00:00+01:00")

    assert not _service_registered(hass)

    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert _service_registered(hass)

    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id)
    assert len(response["electricity"]) == 4

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    # Service registration is component-wide and unaffected by unloading a single entry.
    assert _service_registered(hass)
    with pytest.raises(ServiceValidationError):
        await call_get_prices(hass, config_entry_id=config_entry.entry_id)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert _service_registered(hass)
    response = await call_get_prices(hass, config_entry_id=config_entry.entry_id)
    assert len(response["electricity"]) == 4
