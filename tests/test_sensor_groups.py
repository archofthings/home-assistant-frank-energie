"""Tests for selectable sensor groups (see const.enabled_groups and __init__.py)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.frank_energie import const, price_analysis
from tests.utils import (
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    build_market_prices,
    install_prices,
    local_midnight,
    make_me,
)

PRICE_ANALYSIS_ENTITIES = {
    "sensor": ["price_level", "price_analysis_today", "price_analysis_tomorrow", "next_cheapest_period"],
    "binary_sensor": ["cheap_price_now", "cheapest_period_now"],
}

COST_KEYS = [
    "actual_costs_until_last_meter_reading_date",
    "expected_costs_until_last_meter_reading_date",
    "expected_costs_this_month",
    "invoice_previous_period",
    "invoice_current_period",
    "invoice_upcoming_period",
]


def entity_id_for_key(hass, entry, domain: str, key: str) -> str | None:
    """Look up an entity_id by its unique_id (f'{entry.unique_id}.{key}'), independent of slugging."""
    return er.async_get(hass).async_get_entity_id(domain, const.DOMAIN, f"{entry.unique_id}.{key}")


# --------------------------------------------------------------------------
# enabled_groups(): default to all groups when unset, else the stored set.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "options, expected",
    [
        ({}, set(const.SENSOR_GROUPS)),
        ({const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_UPCOMING]}, {const.SENSOR_GROUP_UPCOMING}),
    ],
    ids=["legacy_entry_without_option", "entry_with_stored_groups"],
)
def test_enabled_groups(options, expected):
    """A legacy entry without sensor_groups defaults to all groups; otherwise the stored set is used as is."""
    entry = MockConfigEntry(domain=const.DOMAIN, data={}, options=options)
    assert const.enabled_groups(entry) == expected


# --------------------------------------------------------------------------
# Disabling/re-enabling a group removes/recreates its entities, with the
# same entity_id (see __init__.py's _async_remove_disabled_group_entities).
# --------------------------------------------------------------------------


async def test_disabling_group_removes_entities_and_reenabling_recreates_them_with_same_entity_id(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """Deselecting "upcoming" removes its entities from the registry; re-selecting recreates the same entity_id."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        options={const.CONF_SENSOR_GROUPS: list(const.SENSOR_GROUPS)},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    original_entity_id = entity_id_for_key(hass, entry, "sensor", "elec_next")
    assert original_entity_id is not None

    hass.config_entries.async_update_entry(
        entry, options={const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_STATISTICS]}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_id_for_key(hass, entry, "sensor", "elec_next") is None
    # Current-price entities (not part of any group) are never touched.
    assert entity_id_for_key(hass, entry, "sensor", "elec_markup") is not None

    hass.config_entries.async_update_entry(entry, options={const.CONF_SENSOR_GROUPS: list(const.SENSOR_GROUPS)})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_id_for_key(hass, entry, "sensor", "elec_next") == original_entity_id


# --------------------------------------------------------------------------
# price_analysis disabled: no PriceAnalysisCoordinator, no analysis entities.
# --------------------------------------------------------------------------


async def test_price_analysis_disabled_creates_no_coordinator_and_no_analysis_entities(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """Without price_analysis in sensor_groups, no PriceAnalysisCoordinator is created and its entities are absent."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        options={const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_STATISTICS]},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.data[const.DOMAIN][entry.entry_id][const.CONF_PRICE_ANALYSIS] is None
    assert entity_id_for_key(hass, entry, "sensor", "price_level") is None
    assert entity_id_for_key(hass, entry, "sensor", "price_analysis_today") is None
    assert entity_id_for_key(hass, entry, "binary_sensor", "cheap_price_now") is None
    # Current-price entities are unaffected.
    assert entity_id_for_key(hass, entry, "sensor", "elec_markup") is not None


# --------------------------------------------------------------------------
# Deselecting price_analysis on a running (already loaded) entry: all 6
# analysis entities disappear and the shared quarter-hour timer is cancelled,
# not just absent for a freshly-created entry (see the disabled-at-setup test
# above).
# --------------------------------------------------------------------------


async def test_disabling_price_analysis_on_running_entry_removes_entities_and_cancels_its_timer(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """Deselecting "price_analysis" on a loaded entry removes all 6 analysis entities and stops its timer."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        options={const.CONF_SENSOR_GROUPS: list(const.SENSOR_GROUPS)},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])

    # Spy on PriceAnalysisCoordinator's own listeners (its price-coordinator
    # subscription and the shared quarter-hour timer, see
    # price_analysis.async_setup_listeners), wrapping each unsub in a
    # MagicMock so call counts can be asserted, without touching
    # homeassistant.helpers.event (also used by sensor.py's own per-entity
    # timers, which are unrelated to this group).
    real_setup_listeners = price_analysis.PriceAnalysisCoordinator.async_setup_listeners
    captured_unsubs = []

    def spy_setup_listeners(self):
        wrapped = [MagicMock(side_effect=unsub) for unsub in real_setup_listeners(self)]
        captured_unsubs.extend(wrapped)
        return wrapped

    with patch.object(price_analysis.PriceAnalysisCoordinator, "async_setup_listeners", spy_setup_listeners):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # The price-coordinator listener and the quarter-hour timer.
    assert len(captured_unsubs) == 2
    assert all(unsub.call_count == 0 for unsub in captured_unsubs)
    for domain, keys in PRICE_ANALYSIS_ENTITIES.items():
        for key in keys:
            assert entity_id_for_key(hass, entry, domain, key) is not None

    hass.config_entries.async_update_entry(
        entry, options={const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_STATISTICS]}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    # Both listeners, including the quarter-hour timer, were cancelled on
    # unload, and no new ones were registered.
    assert all(unsub.call_count == 1 for unsub in captured_unsubs)
    assert hass.data[const.DOMAIN][entry.entry_id][const.CONF_PRICE_ANALYSIS] is None
    for domain, keys in PRICE_ANALYSIS_ENTITIES.items():
        for key in keys:
            assert entity_id_for_key(hass, entry, domain, key) is None
    # Current-price entities are unaffected.
    assert entity_id_for_key(hass, entry, "sensor", "elec_markup") is not None


# --------------------------------------------------------------------------
# Deselecting costs on a logged-in entry: its 6 cost/invoice entities are
# removed, while current-price entities remain.
# --------------------------------------------------------------------------


async def test_disabling_costs_on_logged_in_entry_removes_cost_entities_but_keeps_current_prices(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """Deselecting "costs" on an authenticated entry removes its 6 cost/invoice entities; current prices remain."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-1",
            CONF_ACCESS_TOKEN: FAKE_ACCESS_TOKEN,
            CONF_TOKEN: FAKE_REFRESH_TOKEN,
        },
        options={const.CONF_SENSOR_GROUPS: list(const.SENSOR_GROUPS)},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    market_prices = build_market_prices(local_midnight(), [0.2] * 4, [1.0] * 4)
    mock_frank_energie_class.is_authenticated = True
    mock_frank_energie_class.user_country.return_value = make_me("NL")
    mock_frank_energie_class.user_prices.return_value = market_prices

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for key in COST_KEYS:
        assert entity_id_for_key(hass, entry, "sensor", key) is not None

    hass.config_entries.async_update_entry(
        entry, options={const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_STATISTICS]}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    for key in COST_KEYS:
        assert entity_id_for_key(hass, entry, "sensor", key) is None
    # Current-price entities are unaffected.
    assert entity_id_for_key(hass, entry, "sensor", "elec_markup") is not None
