"""The Frank Energie component."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, Platform, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from python_frank_energie import FrankEnergie
from python_frank_energie.exceptions import AuthException, AuthRequiredException, FrankEnergieException
from python_frank_energie.models import DeliverySite

from .const import CONF_COORDINATOR, CONF_PRICE_ANALYSIS, DOMAIN
from .coordinator import FrankEnergieCoordinator
from .price_analysis import PriceAnalysisCoordinator
from .services import async_setup_services
from .sites import build_site_title, discover_in_delivery_sites

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
    # doesn't need to be checked either.
    price_analysis_coordinator = PriceAnalysisCoordinator(hass, entry, frank_coordinator)
    await price_analysis_coordinator.async_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_COORDINATOR: frank_coordinator,
        CONF_PRICE_ANALYSIS: price_analysis_coordinator,
    }

    for unsub in price_analysis_coordinator.async_setup_listeners():
        entry.async_on_unload(unsub)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
