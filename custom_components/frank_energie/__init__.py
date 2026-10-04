"""The Frank Energie component."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, Platform, CONF_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from python_frank_energie import FrankEnergie
from python_frank_energie.exceptions import AuthException, AuthRequiredException, FrankEnergieException
from python_frank_energie.models import DeliverySite

from .const import (
    DATA_MONTH_SUMMARY,
    DOMAIN,
    SENSOR_GROUP_COSTS,
    SENSOR_GROUP_DAILY_USAGE,
    SENSOR_GROUP_ENERGY_STATISTICS,
    SENSOR_GROUP_MONTHLY_USAGE,
    SENSOR_GROUP_PRICE_ANALYSIS,
    enabled_groups,
    key_enabled,
)
from .contract import ContractCoordinator
from .coordinator import FrankEnergieCoordinator
from .energy_statistics import FrankEnergieStatisticsImporter
from .price_analysis import PriceAnalysisCoordinator
from .services import async_setup_services
from .sites import build_site_title, discover_in_delivery_sites
from .usage import UsageCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class FrankEnergieRuntimeData:
    """Runtime data stored on a Frank Energie config entry (see entry.runtime_data)."""

    coordinator: FrankEnergieCoordinator
    price_analysis: PriceAnalysisCoordinator | None
    usage: UsageCoordinator | None
    contract: ContractCoordinator | None = None


type FrankEnergieConfigEntry = ConfigEntry[FrankEnergieRuntimeData]


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


def _async_setup_cost_data_sync(
    hass: HomeAssistant,
    entry: ConfigEntry,
    frank_coordinator: FrankEnergieCoordinator,
    usage_coordinator: UsageCoordinator | None,
    start_import: Callable[[], None] | None,
) -> None:
    """Refresh the other cost data sources as soon as one of them receives a new value.

    The month summary (hourly), the usage data (every 3 hours) and the statistics import (every 3 hours) are
    polled independently, so the dashboard could show a mix of days. A marker only counts as new when it is
    not None and differs from the last non-None value seen; the initial data never triggers anything.
    """

    def _trigger(coordinator: DataUpdateCoordinator | None) -> None:
        if coordinator is not None:
            entry.async_create_background_task(hass, coordinator.async_request_refresh(), "frank_energie_cost_sync")
        if start_import is not None:
            start_import()

    def _summary_date() -> str | None:
        data = frank_coordinator.data
        summary = data.get(DATA_MONTH_SUMMARY) if data is not None else None
        return summary.lastMeterReadingDate if summary is not None else None

    last_summary_date = _summary_date()

    @callback
    def _on_frank_update() -> None:
        nonlocal last_summary_date
        new_date = _summary_date()
        if new_date is None or new_date == last_summary_date:
            return
        last_summary_date = new_date
        _trigger(usage_coordinator)

    entry.async_on_unload(frank_coordinator.async_add_listener(_on_frank_update))

    if usage_coordinator is not None:
        entry.async_on_unload(
            usage_coordinator.async_add_listener(_usage_update_listener(usage_coordinator, frank_coordinator, _trigger))
        )


def _usage_update_listener(
    usage_coordinator: UsageCoordinator,
    frank_coordinator: FrankEnergieCoordinator,
    trigger: Callable[[DataUpdateCoordinator], None],
) -> Callable[[], None]:
    """Build the usage coordinator listener: trigger a main refresh on a new daily or monthly value."""

    def _markers() -> tuple[date | None, datetime | None]:
        data = usage_coordinator.data
        if data is None:
            return None, None
        daily_date = data.daily_date if data.daily is not None else None
        monthly_date = data.monthly.lastMeterReadingDate if data.monthly is not None else None
        return daily_date, monthly_date

    last = _markers()

    @callback
    def _on_usage_update() -> None:
        nonlocal last
        new = _markers()
        changed = any(n is not None and n != old for n, old in zip(new, last))
        last = tuple(n if n is not None else old for n, old in zip(new, last))
        if changed:
            trigger(frank_coordinator)

    return _on_usage_update


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

    # Same rationale as the price analysis/usage coordinators above: a
    # failure here should not prevent the rest of the integration from
    # loading. Only created for an authenticated entry with the costs
    # sensor group enabled.
    contract_coordinator = None
    if frank_coordinator.api.is_authenticated and SENSOR_GROUP_COSTS in groups:
        contract_coordinator = ContractCoordinator(hass, entry, frank_coordinator)
        await contract_coordinator.async_refresh()

    # Imports hourly usage and costs as Energy dashboard statistics. The first
    # import runs in the background so setup isn't delayed; API errors are logged, not raised.
    start_import = None
    if frank_coordinator.api.is_authenticated and SENSOR_GROUP_ENERGY_STATISTICS in groups:
        importer = FrankEnergieStatisticsImporter(hass, entry, frank_coordinator)

        @callback
        def _start_import(_now=None) -> None:
            entry.async_create_background_task(hass, importer.async_import(), "frank_energie_statistics_import")

        _start_import()
        entry.async_on_unload(async_track_time_interval(hass, _start_import, timedelta(hours=3)))
        start_import = _start_import

    _async_setup_cost_data_sync(hass, entry, frank_coordinator, usage_coordinator, start_import)

    entry.runtime_data = FrankEnergieRuntimeData(
        coordinator=frank_coordinator,
        price_analysis=price_analysis_coordinator,
        usage=usage_coordinator,
        contract=contract_coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
