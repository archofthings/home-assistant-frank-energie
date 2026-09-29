"""The Frank Energie component."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, Platform, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from python_frank_energie import FrankEnergie
from python_frank_energie.exceptions import AuthException, AuthRequiredException, FrankEnergieException
from python_frank_energie.models import DeliverySite

from .const import (
    CONF_COORDINATOR,
    CONF_PRICE_ANALYSIS,
    CONF_USAGE_COORDINATOR,
    DOMAIN,
    SENSOR_GROUP_DAILY_USAGE,
    SENSOR_GROUP_MONTHLY_USAGE,
    SENSOR_GROUP_PRICE_ANALYSIS,
    enabled_groups,
    key_enabled,
)
from .coordinator import FrankEnergieCoordinator
from .price_analysis import PriceAnalysisCoordinator
from .services import async_setup_services
from .sites import build_site_title, discover_in_delivery_sites
from .usage import UsageCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Frank Energie component (services only; the rest is config-entry-based)."""
    async_setup_services(hass)
    return True


async def _async_discover_site(api: FrankEnergie) -> DeliverySite:
    """Find the first delivery site that is currently 'IN_DELIVERY'."""
    try:
        user_sites = await api.UserSites()
    except (AuthException, AuthRequiredException) as ex:
        raise ConfigEntryAuthFailed from ex
    except FrankEnergieException as ex:
        # Covers RequestException, NetworkError and any other library error.
        raise ConfigEntryNotReady("No suitable sites found for this account") from ex

    delivery_sites = discover_in_delivery_sites(user_sites)

    if len(delivery_sites) == 0:
        raise ConfigEntryNotReady("No suitable sites found for this account")

    return delivery_sites[0]


def _async_remove_disabled_group_entities(hass: HomeAssistant, entry: ConfigEntry, groups: set[str]) -> None:
    """Remove this entry's entity registry entries whose sensor group is not in `groups`.

    Current-price entities (absent from SENSOR_GROUP_BY_KEY) are never
    touched. Re-enabling a group later recreates its entities with the same
    unique_id, so Home Assistant assigns them the same entity_id again.
    """
    registry = er.async_get(hass)
    prefix = f"{entry.unique_id}."
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not entity.unique_id.startswith(prefix):
            continue
        key = entity.unique_id[len(prefix):]
        if not key_enabled(key, groups):
            registry.async_remove(entity.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Frank Energie component from a config entry."""

    # For backwards compatibility, set unique ID
    if entry.unique_id is None or entry.unique_id == "frank_energie_component":
        hass.config_entries.async_update_entry(entry, unique_id=str("frank_energie"))

    # Select site-reference, or find first one that has status 'IN_DELIVERY' if not set
    if entry.data.get("site_reference") is None and entry.data.get(CONF_ACCESS_TOKEN) is not None:
        api = FrankEnergie(
            clientsession=async_get_clientsession(hass),
            auth_token=entry.data.get(CONF_ACCESS_TOKEN, None),
            refresh_token=entry.data.get(CONF_TOKEN, None),
        )
        site = await _async_discover_site(api)
        hass.config_entries.async_update_entry(entry, data={**entry.data, "site_reference": site.reference})

        # Update title
        title = build_site_title(site)
        if title is not None:
            hass.config_entries.async_update_entry(entry, title=title)

    groups = enabled_groups(entry)
    _async_remove_disabled_group_entities(hass, entry, groups)

    # Initialise the coordinator and save it as domain-data
    api = FrankEnergie(
        clientsession=async_get_clientsession(hass),
        auth_token=entry.data.get(CONF_ACCESS_TOKEN, None),
        refresh_token=entry.data.get(CONF_TOKEN, None),
    )
    frank_coordinator = FrankEnergieCoordinator(hass, entry, api)

    # Fetch initial data, so we have data when entities subscribe and set up the platform
    await frank_coordinator.async_config_entry_first_refresh()

    # The price analysis coordinator derives its data from frank_coordinator's,
    # so it is never used to gate setup readiness: a failure here should not
    # prevent the rest of the integration (and its other entities) from
    # loading. It refreshes itself, so the initial async_refresh() result
    # doesn't need to be checked either. It is only created at all when the
    # price_analysis sensor group is enabled: no timer, no solar fetch, and
    # no entities otherwise.
    price_analysis_coordinator = None
    if SENSOR_GROUP_PRICE_ANALYSIS in groups:
        price_analysis_coordinator = PriceAnalysisCoordinator(hass, entry, frank_coordinator)
        await price_analysis_coordinator.async_refresh()
        for unsub in price_analysis_coordinator.async_setup_listeners():
            entry.async_on_unload(unsub)

    # Same rationale as the price analysis coordinator above: a failure here
    # should not prevent the rest of the integration from loading. Only
    # created for an authenticated entry with at least one of the two usage
    # sensor groups enabled (both require login; see SENSOR_GROUPS_REQUIRE_LOGIN).
    usage_coordinator = None
    if frank_coordinator.api.is_authenticated and (
        SENSOR_GROUP_DAILY_USAGE in groups or SENSOR_GROUP_MONTHLY_USAGE in groups
    ):
        usage_coordinator = UsageCoordinator(hass, entry, frank_coordinator, groups)
        await usage_coordinator.async_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_COORDINATOR: frank_coordinator,
        CONF_PRICE_ANALYSIS: price_analysis_coordinator,
        CONF_USAGE_COORDINATOR: usage_coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
