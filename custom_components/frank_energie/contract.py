"""Coordinator for the contract price resolution state (see const.SENSOR_GROUP_COSTS)."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from python_frank_energie.exceptions import AuthException, AuthRequiredException, FrankEnergieException
from python_frank_energie.models import ContractPriceResolutionState

from .coordinator import FrankEnergieCoordinator

LOGGER = logging.getLogger(__name__)

ELECTRICITY_SEGMENT = "ELECTRICITY"


class ContractCoordinator(DataUpdateCoordinator[ContractPriceResolutionState | None]):
    """Fetches the contract price resolution state (PT15M/PT60M) for one config entry.

    Reuses the main FrankEnergieCoordinator's api client and site_reference,
    so token renewal and persistence stay with the main coordinator; auth
    errors here are left for the main coordinator's own update cycle to
    handle (see _async_update_data below).
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, price_coordinator: FrankEnergieCoordinator) -> None:
        """Initialize the contract coordinator."""
        self.entry = entry
        self.price_coordinator = price_coordinator
        self._connection_id: str | None = None

        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name="Frank Energie contract",
            update_interval=timedelta(hours=6),
        )

    @property
    def connection_id(self) -> str | None:
        """Return the resolved electricity connection id, or None if it hasn't been resolved yet."""
        return self._connection_id

    async def _async_update_data(self) -> ContractPriceResolutionState | None:
        """Resolve the electricity connection id (once) and fetch the price resolution state."""
        api = self.price_coordinator.api
        site_reference = self.price_coordinator.site_reference

        try:
            if self._connection_id is None:
                connection_id = await self._resolve_electricity_connection_id(api, site_reference)
                if connection_id is None:
                    LOGGER.debug("No electricity connection found for account; will retry next refresh")
                    return None
                self._connection_id = connection_id
        finally:
            # api.user() can renew tokens transparently inside _query(), even
            # when it ultimately raised. Persist them via the price
            # coordinator's own helper so a renewed token is never lost.
            if api.is_authenticated:
                self.price_coordinator._async_persist_tokens()

        return await api.contract_price_resolution_state(self._connection_id)

    @staticmethod
    async def _resolve_electricity_connection_id(api, site_reference: str | None) -> str | None:
        """Return the connectionId of the account's electricity connection, or None if there is none."""
        try:
            user = await api.user(site_reference)
        except (AuthException, AuthRequiredException, FrankEnergieException, ValueError) as ex:
            raise UpdateFailed(ex) from ex

        connection = next((c for c in user.connections if c.segment == ELECTRICITY_SEGMENT), None)
        return connection.connectionId if connection is not None else None
