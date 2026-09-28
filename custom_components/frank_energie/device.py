"""Shared DeviceInfo builder for Frank Energie entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN, SERVICE_NAME_PRICES


def device_info(entry: ConfigEntry, service_name: str = SERVICE_NAME_PRICES) -> DeviceInfo:
    """Build the DeviceInfo for a Frank Energie entity grouped under `service_name`.

    No extra identifier is added for the default "Prices" service, for
    backwards compatibility with entities created before this helper existed.
    """
    identifiers = (
        {(DOMAIN, entry.entry_id)}
        if service_name is SERVICE_NAME_PRICES
        else {(DOMAIN, entry.entry_id, service_name)}
    )

    return DeviceInfo(
        identifiers=identifiers,
        name=f"Frank Energie - {service_name}",
        manufacturer="Frank Energie",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://www.frankenergie.nl/goedkoop",
    )
