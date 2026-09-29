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
    make_energy_category,
    make_me,
    make_period_usage_and_costs,
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
    "costs_this_year",
    "costs_previous_year",
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
        ({}, set(const.LEGACY_SENSOR_GROUPS)),
        ({const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_UPCOMING]}, {const.SENSOR_GROUP_UPCOMING}),
    ],
    ids=["legacy_entry_without_option", "entry_with_stored_groups"],
)
def test_enabled_groups(options, expected):
    """A legacy entry without sensor_groups defaults to LEGACY_SENSOR_GROUPS; otherwise the stored set is used as is."""
    entry = MockConfigEntry(domain=const.DOMAIN, data={}, options=options)
    assert const.enabled_groups(entry) == expected


# --------------------------------------------------------------------------
# Disabling/re-enabling a group removes/recreates its entities, with the
# same entity_id (see __init__.py's _async_remove_disabled_group_entities).
# --------------------------------------------------------------------------


@pytest.mark.parametrize("unique_id", ["frank_energie", "a.b@c.nl"], ids=["fixed_unique_id", "username_unique_id"])
async def test_disabling_group_removes_entities_and_reenabling_recreates_them_with_same_entity_id(
    hass, enable_custom_integrations, mock_frank_energie_class, unique_id
):
    """Deselecting "upcoming" removes its entities from the registry; re-selecting recreates the same entity_id.

    Parametrized with a username-style unique_id containing dots, so the
    prefix-stripping in _async_remove_disabled_group_entities is exercised
    with a unique_id that isn't itself free of dots.
    """
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={"site_reference": "site-1"},
        options={const.CONF_SENSOR_GROUPS: list(const.SENSOR_GROUPS)},
        unique_id=unique_id,
    )
    entry.add_to_hass(hass)
    install_prices(mock_frank_energie_class, [0.2] * 4, [1.0] * 4, tomorrow_electricity=[], tomorrow_gas=[])

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    original_entity_id = entity_id_for_key(hass, entry, "sensor", "elec_next")
    assert original_entity_id is not None
    assert entity_id_for_key(hass, entry, "binary_sensor", "tomorrow_prices_available") is not None

    hass.config_entries.async_update_entry(
        entry, options={const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_STATISTICS]}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_id_for_key(hass, entry, "sensor", "elec_next") is None
    assert entity_id_for_key(hass, entry, "binary_sensor", "tomorrow_prices_available") is None
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

    assert entry.runtime_data.price_analysis is None
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
    assert entry.runtime_data.price_analysis is None
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
    mock_frank_energie_class.user.return_value = MagicMock(
        connections=[MagicMock(segment="ELECTRICITY", connectionId="elec-conn")]
    )
    mock_frank_energie_class.contract_price_resolution_state.return_value = None

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for key in COST_KEYS:
        assert entity_id_for_key(hass, entry, "sensor", key) is not None
    assert entity_id_for_key(hass, entry, "sensor", "price_resolution") is not None

    hass.config_entries.async_update_entry(
        entry, options={const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_STATISTICS]}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    for key in COST_KEYS:
        assert entity_id_for_key(hass, entry, "sensor", key) is None
    assert entity_id_for_key(hass, entry, "sensor", "price_resolution") is None
    # Current-price entities are unaffected.
    assert entity_id_for_key(hass, entry, "sensor", "elec_markup") is not None


@pytest.mark.parametrize(
    "options",
    [{}, {const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_STATISTICS]}],
    ids=["legacy_entry_no_options", "explicit_groups_without_usage"],
)
async def test_neither_usage_group_enabled_creates_no_coordinator_and_makes_no_api_calls(
    hass, enable_custom_integrations, mock_frank_energie_class, options
):
    """With neither usage group enabled (a legacy entry with no options, or an entry whose stored groups don't
    include either), no UsageCoordinator is created, no usage entities exist, and neither
    period_usage_and_costs nor month_insights is called."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-1",
            CONF_ACCESS_TOKEN: FAKE_ACCESS_TOKEN,
            CONF_TOKEN: FAKE_REFRESH_TOKEN,
        },
        options=options,
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    mock_frank_energie_class.is_authenticated = True
    mock_frank_energie_class.user_country.return_value = make_me("NL")
    mock_frank_energie_class.user_prices.return_value = build_market_prices(local_midnight(), [0.2] * 4, [1.0] * 4)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.usage is None
    assert entity_id_for_key(hass, entry, "sensor", "elec_usage_yesterday") is None
    assert entity_id_for_key(hass, entry, "sensor", "elec_usage_month") is None
    mock_frank_energie_class.period_usage_and_costs.assert_not_awaited()
    mock_frank_energie_class.month_insights.assert_not_awaited()


# --------------------------------------------------------------------------
# Enabling daily_usage on a logged-in entry creates its UsageCoordinator and
# entities; disabling it again removes both (see usage.py and __init__.py).
# --------------------------------------------------------------------------


async def test_enabling_daily_usage_creates_coordinator_and_entities_disabling_removes_them(
    hass, enable_custom_integrations, mock_frank_energie_class
):
    """Enabling "daily_usage" creates the UsageCoordinator and its entities; disabling it removes both."""
    entry = MockConfigEntry(
        domain=const.DOMAIN,
        data={
            "site_reference": "site-1",
            CONF_ACCESS_TOKEN: FAKE_ACCESS_TOKEN,
            CONF_TOKEN: FAKE_REFRESH_TOKEN,
        },
        options={const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_STATISTICS]},
        unique_id="frank_energie",
    )
    entry.add_to_hass(hass)
    mock_frank_energie_class.is_authenticated = True
    mock_frank_energie_class.user_country.return_value = make_me("NL")
    mock_frank_energie_class.user_prices.return_value = build_market_prices(local_midnight(), [0.2] * 4, [1.0] * 4)
    mock_frank_energie_class.period_usage_and_costs.return_value = make_period_usage_and_costs(
        electricity=make_energy_category(10.0, 2.5)
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.usage is None
    assert entity_id_for_key(hass, entry, "sensor", "elec_usage_yesterday") is None

    hass.config_entries.async_update_entry(
        entry, options={const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_USAGE]}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.usage is not None
    assert entity_id_for_key(hass, entry, "sensor", "elec_usage_yesterday") is not None

    hass.config_entries.async_update_entry(
        entry, options={const.CONF_SENSOR_GROUPS: [const.SENSOR_GROUP_DAILY_STATISTICS]}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.usage is None
    assert entity_id_for_key(hass, entry, "sensor", "elec_usage_yesterday") is None
