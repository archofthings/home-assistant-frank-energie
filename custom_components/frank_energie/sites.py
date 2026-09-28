"""Shared helpers for working with Frank Energie delivery sites.

Used by both __init__.py (automatic site discovery for entries without a
stored site_reference) and config_flow.py (choosing a site at login time and
via reconfigure).
"""
from __future__ import annotations

from python_frank_energie.models import DeliverySite, UserSites


def build_site_title(site: DeliverySite) -> str | None:
    """Build a config entry title from a delivery site's address.

    Returns None when the site has no address (e.g. after a house move), so
    callers can fall back to something else (e.g. the username).
    """
    if site.address is None:
        return None

    title = f"{site.address.street} {site.address.houseNumber}"
    if site.address.houseNumberAddition is not None:
        title += f" {site.address.houseNumberAddition}"
    return title


def discover_in_delivery_sites(user_sites: UserSites) -> list[DeliverySite]:
    """Return the delivery sites that are currently 'IN_DELIVERY', skipping None entries."""
    return [site for site in user_sites.deliverySites if site is not None and site.status == "IN_DELIVERY"]
