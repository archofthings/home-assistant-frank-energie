"""Pure price-analysis calculations for Frank Energie electricity prices.

Everything in this module is a plain function/dataclass with no dependency on
Home Assistant (`hass`) or the coordinator, so it is fully unit-testable in
isolation. See `price_analysis.py` for the `hass`-aware manager that wires
this module up to the coordinator and the solar forecast.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Iterable, Protocol

from .const import (
    PRICE_LEVEL_CHEAP,
    PRICE_LEVEL_CHEAP_SOLAR,
    PRICE_LEVEL_EXPENSIVE,
    PRICE_LEVEL_NORMAL,
)


class PriceSlot(Protocol):
    """The minimal shape `find_cheapest_period` needs from a price slot.

    `python_frank_energie.models.Price` satisfies this protocol, so the
    coordinator's price slots can be passed in directly.
    """

    date_from: datetime
    date_till: datetime
    total: float


@dataclass(frozen=True)
class ClassifiedSlot:
    """A single price slot together with its computed level and solar forecast."""

    date_from: datetime
    date_till: datetime
    price: float
    level: str
    solar_kwh: float


@dataclass(frozen=True)
class Window:
    """A contiguous block of slots, e.g. a cheapest period or a cheap/expensive window."""

    start: datetime
    end: datetime
    average_price: float
    minutes: int
    average_solar_kwh: float | None = None


def classify(
    price: float,
    cheap: float,
    expensive: float,
    solar_kwh_per_hour: float,
    solar_threshold: float,
) -> str:
    """Classify a single slot's price into a level.

    - "expensive" if `price` is strictly greater than `expensive`.
    - "cheap_solar" if `price <= cheap` and `solar_kwh_per_hour >= solar_threshold`.
    - "cheap" if `price <= cheap` (and the solar condition above doesn't hold).
    - "normal" otherwise.
    """
    if price > expensive:
        return PRICE_LEVEL_EXPENSIVE
    if price <= cheap:
        if solar_kwh_per_hour >= solar_threshold:
            return PRICE_LEVEL_CHEAP_SOLAR
        return PRICE_LEVEL_CHEAP
    return PRICE_LEVEL_NORMAL


def _parse_forecast_entries(wh_hours: dict[str, float], reference_tz) -> list[tuple[datetime, float]]:
    """Parse `wh_hours` into a sorted list of (period start, Wh) pairs, skipping malformed entries.

    A key that doesn't parse as an ISO timestamp, or a value that doesn't
    parse as a float, is skipped individually (see `solar_per_slot`).
    """
    forecast: list[tuple[datetime, float]] = []
    for key, value in wh_hours.items():
        try:
            start = datetime.fromisoformat(key)
            wh = float(value)
        except (TypeError, ValueError):
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=reference_tz)
        forecast.append((start, wh))
    forecast.sort(key=lambda item: item[0])
    return forecast


def _forecast_periods(forecast: list[tuple[datetime, float]]) -> list[tuple[datetime, float, float]]:
    """Turn a sorted (start, Wh) forecast into (start, Wh, length_minutes) periods.

    Each period's length is the gap to the *next* entry, capped at 60
    minutes; the last (or only) entry falls back to a 60 minute period (see
    `solar_per_slot`).
    """
    periods: list[tuple[datetime, float, float]] = []
    for index, (start, wh) in enumerate(forecast):
        if index + 1 < len(forecast):
            length_minutes = min((forecast[index + 1][0] - start).total_seconds() / 60, 60.0)
        else:
            length_minutes = 60.0
        if length_minutes <= 0:
            continue
        periods.append((start, wh, length_minutes))
    return periods


def _solar_kwh_for_slot(at: datetime, periods: list[tuple[datetime, float, float]]) -> float:
    """Return the solar forecast (kWh/h) for the period in `periods` that contains `at`, or 0.0."""
    for start, value, length_minutes in periods:
        if start <= at < start + timedelta(minutes=length_minutes):
            return (value / 1000) * 60 / length_minutes
    return 0.0


def solar_per_slot(slots: Iterable[PriceSlot], wh_hours: dict[str, float]) -> dict[datetime, float]:
    """Map each slot's `date_from` to a solar forecast in kWh per hour.

    `wh_hours` is the raw forecast as returned by an energy platform's
    `async_get_solar_forecast`: keys are ISO timestamps of forecast period
    *starts* (mapping to a Wh total produced during that period). Periods can
    be irregular: e.g. Forecast.Solar places a period at the (odd-minute)
    sunrise/sunset time, surrounded by regular hourly (or half-hourly)
    periods elsewhere in the same day. Each period's length is therefore
    derived individually, from the gap to the *next* sorted key, capped at 60
    minutes; the last (or only) entry, and any gap between two keys longer
    than 60 minutes (e.g. overnight), falls back to a 60 minute period.
    Forecast keys without timezone info are assumed to be in the same
    timezone as the slots' `date_from` values. A malformed entry (a key that
    doesn't parse as an ISO timestamp, or a value that doesn't parse as a
    float) is skipped individually, so a partially malformed forecast only
    loses solar data for the affected period(s) instead of the whole result.

    Each slot is mapped to the forecast period that contains its `date_from`.
    A slot with no matching forecast period (e.g. the forecast doesn't cover
    that far ahead) gets 0.0.

    Period-start evidence (Forecast.Solar): the `forecast_solar` library's
    `Estimate.energy_current_hour` sums every `wh_period` entry whose
    timestamp falls in `[hour_start, hour_start + 1h)` to get that hour's
    production. That only equals the hour's total if each key marks when its
    period *starts* -- an "ends" key would need the complementary
    `(hour_start, hour_start + 1h]` range instead.
    """
    slots = list(slots)
    if not slots:
        return {}
    if not wh_hours:
        return {slot.date_from: 0.0 for slot in slots}

    reference_tz = slots[0].date_from.tzinfo
    forecast = []
    for key, value in wh_hours.items():
        start = datetime.fromisoformat(key)
        if start.tzinfo is None:
            start = start.replace(tzinfo=reference_tz)
        forecast.append((start, float(value)))
    forecast.sort(key=lambda item: item[0])

    if len(forecast) >= 2:
        period_minutes = round((forecast[1][0] - forecast[0][0]).total_seconds() / 60)
    else:
        period_minutes = 60

    result: dict[datetime, float] = {}
    for slot in slots:
        wh = 0.0
        for start, value in forecast:
            if start <= slot.date_from < start + timedelta(minutes=period_minutes):
                wh = value
                break
        result[slot.date_from] = (wh / 1000) * 60 / period_minutes

    return result


def _split_contiguous_runs(slots: list[PriceSlot]) -> list[list[PriceSlot]]:
    """Split a date_from-sorted slot list into runs where each date_from == the previous date_till."""
    runs: list[list[PriceSlot]] = [[slots[0]]]
    for previous, current in zip(slots, slots[1:]):
        if current.date_from == previous.date_till:
            runs[-1].append(current)
        else:
            runs.append([current])
    return runs


def _best_window_in_run(run: list[PriceSlot], minutes: int) -> Window | None:
    """Return the cheapest-average window of (at least) `minutes` within one contiguous run.

    The window length is rounded up to a whole number of slots: e.g. 45
    minutes requested with 60-minute slots yields a 60-minute window. `run`
    is assumed to already be sorted and contiguous. Returns None when `run`
    has fewer slots than the rounded-up window needs.
    """
    slot_minutes = round((run[0].date_till - run[0].date_from).total_seconds() / 60)
    if slot_minutes <= 0:
        return None

    slot_count = -(-minutes // slot_minutes)  # ceil division: round up to whole slots
    if len(run) < slot_count:
        return None

    best: Window | None = None
    for i in range(len(run) - slot_count + 1):
        window_slots = run[i:i + slot_count]
        average_price = mean(slot.total for slot in window_slots)
        if best is None or average_price < best.average_price:
            best = Window(
                start=window_slots[0].date_from,
                end=window_slots[-1].date_till,
                average_price=average_price,
                minutes=slot_count * slot_minutes,
            )

    return best


def find_cheapest_period(
    slots: Iterable[PriceSlot], minutes: int, not_before: datetime | None = None
) -> Window | None:
    """Find the contiguous block of slots covering (at least) `minutes` with the lowest average price.

    Contiguous means each slot's `date_from` equals the previous slot's
    `date_till`; a gap between slots is never bridged. When `minutes` isn't a
    multiple of the slot length, the window is rounded up to whole slots (see
    `_best_window_in_run`). Ties (equal average price) go to the earliest
    candidate window. Returns None when there are no slots, or none of the
    contiguous runs is long enough to hold a window.

    When `not_before` is given, only slots with `date_till > not_before` are
    considered.
    """
    candidates = sorted(
        (slot for slot in slots if not_before is None or slot.date_till > not_before),
        key=lambda slot: slot.date_from,
    )
    if not candidates:
        return None

    best: Window | None = None
    for run in _split_contiguous_runs(candidates):
        window = _best_window_in_run(run, minutes)
        if window is None:
            continue
        if best is None or window.average_price < best.average_price:
            best = window

    return best


def _group_by_predicate(slots: list[ClassifiedSlot], predicate, with_solar: bool) -> list[Window]:
    """Merge consecutive (and contiguous) slots matching `predicate` into windows."""
    windows: list[Window] = []
    run: list[ClassifiedSlot] = []

    for slot in slots:
        contiguous = bool(run) and slot.date_from == run[-1].date_till
        if predicate(slot) and (not run or contiguous):
            run.append(slot)
            continue

        if run:
            windows.append(_window_from_run(run, with_solar))
        run = [slot] if predicate(slot) else []

    if run:
        windows.append(_window_from_run(run, with_solar))

    return windows


def _window_from_run(run: list[ClassifiedSlot], with_solar: bool) -> Window:
    start = run[0].date_from
    end = run[-1].date_till
    return Window(
        start=start,
        end=end,
        average_price=mean(slot.price for slot in run),
        minutes=round((end - start).total_seconds() / 60),
        average_solar_kwh=mean(slot.solar_kwh for slot in run) if with_solar else None,
    )


def group_windows(classified_slots: Iterable[ClassifiedSlot]) -> tuple[list[Window], list[Window], list[Window]]:
    """Group classified slots into cheap, expensive and solar windows.

    Returns `(cheap_windows, expensive_windows, solar_windows)`:
    - cheap windows merge consecutive "cheap" and "cheap_solar" slots,
    - expensive windows merge consecutive "expensive" slots,
    - solar windows merge consecutive "cheap_solar" slots (with `average_solar_kwh` set).

    Slots are sorted by `date_from` first; a window never bridges a gap
    (`date_from` must equal the previous slot's `date_till`), matching
    `find_cheapest_period`'s definition of "contiguous".
    """
    slots = sorted(classified_slots, key=lambda slot: slot.date_from)

    cheap_windows = _group_by_predicate(
        slots, lambda slot: slot.level in (PRICE_LEVEL_CHEAP, PRICE_LEVEL_CHEAP_SOLAR), with_solar=False
    )
    expensive_windows = _group_by_predicate(
        slots, lambda slot: slot.level == PRICE_LEVEL_EXPENSIVE, with_solar=False
    )
    solar_windows = _group_by_predicate(
        slots, lambda slot: slot.level == PRICE_LEVEL_CHEAP_SOLAR, with_solar=True
    )

    return cheap_windows, expensive_windows, solar_windows
