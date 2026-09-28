"""Unit tests for the pure price-analysis calculations in analysis.py."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.frank_energie.analysis import (
    ClassifiedSlot,
    classify,
    find_cheapest_period,
    group_windows,
    solar_per_slot,
)

UTC = timezone.utc


@dataclass
class _Slot:
    """A minimal stand-in for python_frank_energie.models.Price (date_from/date_till/total only)."""

    date_from: datetime
    date_till: datetime
    total: float


def _slots(start: datetime, prices: list[float], minutes: int = 15) -> list[_Slot]:
    """Build a contiguous list of `_Slot`s starting at `start`, one per price in `prices`."""
    step = timedelta(minutes=minutes)
    return [_Slot(start + i * step, start + (i + 1) * step, price) for i, price in enumerate(prices)]


# --------------------------------------------------------------------------
# classify
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "price, cheap, expensive, solar_kwh, solar_threshold, expected",
    [
        (0.40, 0.25, 0.40, 0.0, 1.5, "normal"),  # at expensive threshold: not (yet) expensive
        (0.4001, 0.25, 0.40, 0.0, 1.5, "expensive"),  # just above expensive threshold
        (0.25, 0.25, 0.40, 0.0, 1.5, "cheap"),  # at cheap threshold: cheap
        (0.2501, 0.25, 0.40, 0.0, 1.5, "normal"),  # just above cheap threshold: normal
        (0.10, 0.25, 0.40, 1.5, 1.5, "cheap_solar"),  # cheap, solar forecast at threshold
        (0.10, 0.25, 0.40, 1.49, 1.5, "cheap"),  # cheap, solar forecast just below threshold
    ],
    ids=[
        "at_expensive_threshold_is_not_expensive",
        "above_expensive_threshold_is_expensive",
        "at_cheap_threshold_is_cheap",
        "above_cheap_threshold_is_normal",
        "cheap_with_solar_at_threshold_is_cheap_solar",
        "cheap_with_solar_below_threshold_is_cheap",
    ],
)
def test_classify_boundaries(price, cheap, expensive, solar_kwh, solar_threshold, expected):
    """classify() applies the documented boundary rules (>, <=, >=) exactly."""
    assert classify(price, cheap, expensive, solar_kwh, solar_threshold) == expected


# --------------------------------------------------------------------------
# find_cheapest_period
# --------------------------------------------------------------------------


def test_find_cheapest_period_basic():
    """The cheapest contiguous 30-minute window is found among several 15-minute slots."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    slots = _slots(start, [0.3, 0.3, 0.1, 0.1, 0.3, 0.3])

    window = find_cheapest_period(slots, minutes=30)

    assert window.start == start + timedelta(minutes=30)
    assert window.end == start + timedelta(minutes=60)
    assert window.average_price == pytest.approx(0.1)
    assert window.minutes == 30


def test_find_cheapest_period_tie_goes_to_earlier():
    """When two windows tie on average price, the earlier one wins."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    slots = _slots(start, [0.1, 0.1, 0.3, 0.1, 0.1])

    window = find_cheapest_period(slots, minutes=30)

    assert window.start == start
    assert window.average_price == pytest.approx(0.1)


def test_find_cheapest_period_respects_not_before():
    """Slots with date_till <= not_before are excluded from consideration."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    slots = _slots(start, [0.1, 0.1, 0.3, 0.3])
    not_before = start + timedelta(minutes=30)

    window = find_cheapest_period(slots, minutes=30, not_before=not_before)

    assert window.start == start + timedelta(minutes=30)
    assert window.average_price == pytest.approx(0.3)


def test_find_cheapest_period_does_not_bridge_a_gap():
    """A gap between slots (date_from != previous date_till) is never bridged into one window."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    slot0 = _Slot(start, start + timedelta(minutes=15), 0.1)
    slot1 = _Slot(start + timedelta(minutes=30), start + timedelta(minutes=45), 0.1)

    window = find_cheapest_period([slot0, slot1], minutes=30)

    assert window is None


@pytest.mark.parametrize("slot_count", [92, 100], ids=["spring_forward_92_slots", "fall_back_100_slots"])
def test_find_cheapest_period_handles_dst_length_days(slot_count):
    """A 92-slot (23h) or 100-slot (25h) DST day is handled like any other contiguous run."""
    start = datetime(2024, 3, 31, tzinfo=UTC)
    prices = [0.3] * slot_count
    cheap_index = slot_count - 5
    for i in range(cheap_index, cheap_index + 4):
        prices[i] = 0.1
    slots = _slots(start, prices)

    window = find_cheapest_period(slots, minutes=60)

    assert window.start == slots[cheap_index].date_from
    assert window.average_price == pytest.approx(0.1)


def test_find_cheapest_period_rounds_up_to_whole_slots():
    """A 45-minute request with 60-minute slots rounds up to a single 60-minute slot."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    slots = _slots(start, [0.5, 0.5, 0.1, 0.5], minutes=60)

    window = find_cheapest_period(slots, minutes=45)

    assert window.minutes == 60
    assert window.start == start + timedelta(hours=2)
    assert window.average_price == pytest.approx(0.1)


# --------------------------------------------------------------------------
# group_windows
# --------------------------------------------------------------------------


def test_group_windows():
    """Consecutive cheap/cheap_solar, expensive and cheap_solar slots are merged into windows."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    classified = [
        ClassifiedSlot(start, start + timedelta(minutes=15), 0.10, "cheap", 0.5),
        ClassifiedSlot(start + timedelta(minutes=15), start + timedelta(minutes=30), 0.05, "cheap_solar", 2.0),
        ClassifiedSlot(start + timedelta(minutes=30), start + timedelta(minutes=45), 0.35, "normal", 0.0),
        ClassifiedSlot(start + timedelta(minutes=45), start + timedelta(minutes=60), 0.50, "expensive", 0.0),
        ClassifiedSlot(start + timedelta(minutes=60), start + timedelta(minutes=75), 0.55, "expensive", 0.0),
    ]

    cheap_windows, expensive_windows, solar_windows = group_windows(classified)

    assert len(cheap_windows) == 1
    assert cheap_windows[0].start == start
    assert cheap_windows[0].end == start + timedelta(minutes=30)
    assert cheap_windows[0].average_price == pytest.approx((0.10 + 0.05) / 2)
    assert cheap_windows[0].average_solar_kwh is None

    assert len(expensive_windows) == 1
    assert expensive_windows[0].start == start + timedelta(minutes=45)
    assert expensive_windows[0].end == start + timedelta(minutes=75)
    assert expensive_windows[0].average_price == pytest.approx((0.50 + 0.55) / 2)

    assert len(solar_windows) == 1
    assert solar_windows[0].start == start + timedelta(minutes=15)
    assert solar_windows[0].end == start + timedelta(minutes=30)
    assert solar_windows[0].average_solar_kwh == pytest.approx(2.0)


# --------------------------------------------------------------------------
# solar_per_slot
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "period_minutes, wh1, wh2",
    [(60, 1000.0, 500.0), (30, 1000.0, 500.0)],
    ids=["60_minute_forecast_periods", "30_minute_forecast_periods"],
)
def test_solar_per_slot_normalizes_wh_to_kwh_per_hour(period_minutes, wh1, wh2):
    """solar_per_slot normalizes Wh-per-forecast-period into kWh/hour, for 60- and 30-minute periods."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    slot_count = (2 * period_minutes) // 15  # two forecast periods' worth of 15-minute slots
    slots = _slots(start, [0.2] * slot_count)
    wh_hours = {
        start.isoformat(): wh1,
        (start + timedelta(minutes=period_minutes)).isoformat(): wh2,
    }

    result = solar_per_slot(slots, wh_hours)

    expected1 = (wh1 / 1000) * 60 / period_minutes
    expected2 = (wh2 / 1000) * 60 / period_minutes
    half = slot_count // 2
    for slot in slots[:half]:
        assert result[slot.date_from] == pytest.approx(expected1)
    for slot in slots[half:]:
        assert result[slot.date_from] == pytest.approx(expected2)


def test_solar_per_slot_missing_forecast_is_zero():
    """A slot with no matching forecast period gets 0.0 kWh/h."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    slots = _slots(start, [0.2])

    assert solar_per_slot(slots, {}) == {slots[0].date_from: 0.0}
