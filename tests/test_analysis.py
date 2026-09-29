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
    """solar_per_slot normalizes Wh-per-forecast-period into kWh/hour, for 60- and 30-minute periods.

    A third (empty) forecast key bounds the second period's length via the
    regular key spacing, rather than the last-entry 60-minute fallback (that
    fallback is exercised separately, see
    `test_solar_per_slot_last_entry_falls_back_to_a_60_minute_period`).
    """
    start = datetime(2024, 1, 1, tzinfo=UTC)
    slot_count = (2 * period_minutes) // 15  # two forecast periods' worth of 15-minute slots
    slots = _slots(start, [0.2] * slot_count)
    wh_hours = {
        start.isoformat(): wh1,
        (start + timedelta(minutes=period_minutes)).isoformat(): wh2,
        (start + timedelta(minutes=2 * period_minutes)).isoformat(): 0.0,
    }

    result = solar_per_slot(slots, wh_hours)

    expected1 = (wh1 / 1000) * 60 / period_minutes
    expected2 = (wh2 / 1000) * 60 / period_minutes
    half = slot_count // 2
    for slot in slots[:half]:
        assert result[slot.date_from] == pytest.approx(expected1)
    for slot in slots[half:]:
        assert result[slot.date_from] == pytest.approx(expected2)


def test_solar_per_slot_last_entry_falls_back_to_a_60_minute_period():
    """The last forecast entry (no next key to derive a length from) is treated as a 60-minute period."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    slots = _slots(start, [0.2, 0.2, 0.2, 0.2])  # four 15-minute slots covering the hour
    wh_hours = {start.isoformat(): 300.0}

    result = solar_per_slot(slots, wh_hours)

    for slot in slots:
        assert result[slot.date_from] == pytest.approx(0.3)  # 300 Wh / 60 min == 0.3 kWh/h


def test_solar_per_slot_handles_irregular_period_lengths():
    """Regression (C2): an irregular (e.g. sunrise) period next to regular hourly ones normalizes correctly.

    Forecast.Solar places a period at the (odd-minute) sunrise time; a global
    period length derived from the first two keys' spacing would misapply
    that short period's length to the following regular hourly periods,
    scaling their values up and leaving the trailing quarters unmatched (0).
    """
    start = datetime(2024, 1, 1, 5, 32, tzinfo=UTC)  # 05:32 sunrise
    hour_start = datetime(2024, 1, 1, 6, 0, tzinfo=UTC)  # 06:00, the next (regular, 60-minute) period
    wh_hours = {
        start.isoformat(): 0.0,  # 05:32-06:00 (28 minutes): negligible production just after sunrise
        hour_start.isoformat(): 200.0,  # 06:00-07:00 (60 minutes): 200 Wh
        (hour_start + timedelta(hours=1)).isoformat(): 2000.0,  # 07:00 onward: 2000 Wh (60-minute fallback)
    }
    slots = _slots(hour_start, [0.2, 0.2, 0.2, 0.2], minutes=15)  # 06:00, 06:15, 06:30, 06:45

    result = solar_per_slot(slots, wh_hours)

    for slot in slots:
        assert result[slot.date_from] == pytest.approx(0.2)  # 200 Wh / 60 min == 0.2 kWh/h, for all four quarters


def test_solar_per_slot_missing_forecast_is_zero():
    """A slot with no matching forecast period gets 0.0 kWh/h."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    slots = _slots(start, [0.2])

    assert solar_per_slot(slots, {}) == {slots[0].date_from: 0.0}


def test_solar_per_slot_skips_malformed_entries():
    """A malformed forecast entry (bad key or value) is skipped instead of raising (W1)."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    good_start = start + timedelta(minutes=60)
    slots = _slots(good_start, [0.2, 0.2, 0.2, 0.2], minutes=15)
    wh_hours = {
        "not-a-timestamp": 500.0,
        start.isoformat(): "not-a-number",
        good_start.isoformat(): 240.0,
    }

    result = solar_per_slot(slots, wh_hours)

    for slot in slots:
        assert result[slot.date_from] == pytest.approx(0.24)  # only the well-formed 240 Wh/60 min entry applies


@pytest.mark.parametrize(
    "slot_start_offset, slot_minutes, wh_hours_offsets, expected_kwh_per_hour",
    [
        (0, 60, {0: 500.0, 30: 1000.0, 60: 0.0}, 1.5),
        (0, 15, {0: 240.0, 60: 0.0}, 0.24),
        (30, 60, {0: 500.0}, 0.25),
    ],
    ids=[
        "60min_slot_averages_two_30min_periods",
        "15min_slot_inside_60min_period_is_unchanged",
        "60min_slot_half_covered_averages_with_zero",
    ],
)
def test_solar_per_slot_time_weighted_average_over_slot(
    slot_start_offset, slot_minutes, wh_hours_offsets, expected_kwh_per_hour
):
    """solar_per_slot averages overlapping forecast periods over the whole slot, weighted by overlap minutes.

    - A 60-minute slot spanning two 30-minute forecast periods (500 Wh then
      1000 Wh) gets their time-weighted average, not just the first period's
      value (regression: previously only the period containing the slot's
      `date_from` was used).
    - A 15-minute slot fully inside a single 60-minute forecast period is
      unaffected by the change.
    - A 60-minute slot only half covered by forecast data is averaged with
      0.0 for the uncovered half.
    """
    reference = datetime(2024, 1, 1, tzinfo=UTC)
    slot_start = reference + timedelta(minutes=slot_start_offset)
    slots = [_Slot(slot_start, slot_start + timedelta(minutes=slot_minutes), 0.2)]
    wh_hours = {
        (reference + timedelta(minutes=offset)).isoformat(): wh for offset, wh in wh_hours_offsets.items()
    }

    result = solar_per_slot(slots, wh_hours)

    assert result[slot_start] == pytest.approx(expected_kwh_per_hour)
