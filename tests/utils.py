"""Test helpers for building python-frank-energie model objects.

These helpers build real ``python_frank_energie.models`` instances (PriceData,
MarketPrices, ...) from simple Python values, so tests never need to hand-craft
the raw GraphQL response payloads the library itself parses.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util
from python_frank_energie.models import Address, DeliverySite, MarketPrices, PriceData, UserSites

# A non-JWT-shaped token. python_frank_energie's Authentication.is_expired
# treats any auth token that doesn't look like a JWT (3 dot-separated parts)
# as "not expired", so plain strings like this are sufficient to make
# FrankEnergie.is_authenticated True without needing to mint real JWTs.
FAKE_ACCESS_TOKEN = "test-access-token"
FAKE_REFRESH_TOKEN = "test-refresh-token"


def price_dicts(
    start: datetime,
    prices: list[float],
    resolution_minutes: int = 60,
    per_unit: str = "kWh",
) -> list[dict]:
    """Build a list of raw price dicts as the FrankEnergie API would return them.

    The coefficients below are chosen so that ``total`` (market + tax +
    sourcing markup + energy tax) equals the input price exactly
    (0.7 + 0.05 + 0.1 + 0.15 == 1.0), which keeps test assertions simple.
    """
    step = timedelta(minutes=resolution_minutes)
    return [
        {
            "from": (start + i * step).isoformat(),
            "till": (start + (i + 1) * step).isoformat(),
            "marketPrice": round(0.7 * price, 6),
            "marketPriceTax": round(0.05 * price, 6),
            "sourcingMarkupPrice": round(0.1 * price, 6),
            "energyTaxPrice": round(0.15 * price, 6),
            "perUnit": per_unit,
        }
        for i, price in enumerate(prices)
    ]


def build_price_data(
    start: datetime,
    prices: list[float],
    energy_type: str,
    resolution_minutes: int = 60,
) -> PriceData:
    """Build a real ``PriceData`` instance from a list of prices."""
    return PriceData(
        price_dicts(start, prices, resolution_minutes),
        energy_type=energy_type,
    )


def build_market_prices(
    start: datetime,
    electricity_prices: list[float],
    gas_prices: list[float],
    energy_country: str = "NL",
    resolution_minutes: int = 60,
) -> MarketPrices:
    """Build a real ``MarketPrices`` instance from lists of prices."""
    return MarketPrices(
        electricity=build_price_data(start, electricity_prices, "electricity", resolution_minutes),
        gas=build_price_data(start, gas_prices, "gas", resolution_minutes),
        energy_country=energy_country,
    )


def make_delivery_site(
    reference: str,
    status: str,
    street: str = "Teststraat",
    house_number: str = "12",
    addition: str | None = None,
) -> DeliverySite:
    """Build a real ``DeliverySite`` instance with a simple address."""
    address = Address(
        street=street,
        houseNumber=house_number,
        zipCode="1234 AB",
        city="Amsterdam",
        houseNumberAddition=addition,
    )
    return DeliverySite(
        addressHasMultipleSites=False,
        propositionType=None,
        reference=reference,
        segments=["ELECTRICITY", "GAS"],
        address=address,
        status=status,
        deliveryStartDate=None,
        deliveryEndDate=None,
        firstMeterReadingDate=None,
        lastMeterReadingDate=None,
    )


def make_user_sites(sites: list[DeliverySite]) -> UserSites:
    """Build a real ``UserSites`` instance wrapping the given delivery sites."""
    first = sites[0] if sites else None
    return UserSites(
        deliverySites=sites,
        addressFormatted="x",
        addressHasMultipleSites=False,
        deliveryEndDate=None,
        deliveryStartDate=None,
        firstMeterReadingDate=None,
        lastMeterReadingDate=None,
        propositionType=None,
        reference=first.reference if first else "",
        segments=[],
        status="IN_DELIVERY",
    )


def price_generator(base: float, var: float, count: int = 24) -> list:
    """Return a list of prices which has two peaks of price `base` and bottoms of `base - 6 * var`."""
    return [round(base - var * abs(6 - (i % 12)), 3) for i in range(count)]


def build_price_data_from_local_midnight(
    local_midnight: datetime,
    prices: list[float],
    energy_type: str,
    resolution_minutes: int = 15,
) -> PriceData:
    """Build a real ``PriceData`` instance for N slots starting at a local midnight.

    Unlike ``build_price_data``, slots are stepped in fixed real-time (UTC)
    increments rather than local wall-clock increments: ``local_midnight`` (an
    aware datetime, typically in a DST-observing zone such as Europe/Amsterdam)
    is first converted to UTC, and ``prices`` is then laid out from there via
    ``build_price_data``. This lets tests model DST transition days correctly:
    a "spring forward" day needs fewer slots to cover the same local calendar
    day and a "fall back" day needs more (e.g. 100 PT15M slots for a 25-hour
    day), matching how the Frank Energie API represents such days.
    """
    start_utc = local_midnight.astimezone(dt_util.UTC)
    return build_price_data(start_utc, prices, energy_type, resolution_minutes)


def build_market_prices_from_local_midnight(
    local_midnight: datetime,
    electricity_prices: list[float],
    gas_prices: list[float],
    energy_country: str = "NL",
    resolution_minutes: int = 15,
) -> MarketPrices:
    """Build a real ``MarketPrices`` instance for N slots starting at a local midnight.

    See ``build_price_data_from_local_midnight`` for why this steps in UTC
    rather than local wall-clock time.
    """
    return MarketPrices(
        electricity=build_price_data_from_local_midnight(
            local_midnight, electricity_prices, "electricity", resolution_minutes
        ),
        gas=build_price_data_from_local_midnight(local_midnight, gas_prices, "gas", resolution_minutes),
        energy_country=energy_country,
    )
