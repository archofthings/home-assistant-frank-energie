"""Tests for selectable sensor groups (see const.enabled_groups and __init__.py)."""
from __future__ import annotations

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.frank_energie import const
from tests.utils import install_prices


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
