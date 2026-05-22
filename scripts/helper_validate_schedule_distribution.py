#!/usr/bin/env python3
"""Validate the flight schedule distribution curve.

Prints the hourly distribution of departures for a generated schedule,
verifying that the realistic traffic curve produces a steady flow
throughout the day rather than sparse bimodal peaks.

Usage:
    python3 scripts/helper_validate_schedule_distribution.py
"""

from collections import Counter
from datetime import date, datetime, time, timedelta

import numpy as np


def sample_departure_slots_standalone(n: int, sim_date: date, np_rng: np.random.Generator) -> list[datetime]:
    """Standalone copy of the schedule generation function for validation."""
    hourly_weights = {
        5: 2, 6: 8, 7: 14, 8: 16, 9: 12, 10: 10, 11: 9,
        12: 8, 13: 9, 14: 10, 15: 10, 16: 12,
        17: 15, 18: 14, 19: 10, 20: 7, 21: 5, 22: 3,
    }
    hours_list = sorted(hourly_weights.keys())
    weights = np.array([hourly_weights[h] for h in hours_list], dtype=float)
    weights /= weights.sum()

    counts = np.round(weights * n).astype(int)
    diff = n - counts.sum()
    if diff != 0:
        idx = int(np.argmax(counts))
        counts[idx] += diff

    slots: list[datetime] = []
    for hour, count in zip(hours_list, counts):
        if count <= 0:
            continue
        minutes = np_rng.uniform(0, 59.99, size=count)
        for m in sorted(minutes):
            minute = round(float(m) / 5) * 5
            if minute >= 60:
                minute = 55
            slots.append(datetime.combine(sim_date, time(hour=hour, minute=minute)))

    slots.sort()
    return slots


def main():
    sim_date = date(2024, 6, 15)
    np_rng = np.random.default_rng(42)

    slots = sample_departure_slots_standalone(210, sim_date, np_rng)

    # Count departures per hour
    hour_counts: Counter[int] = Counter()
    for slot in slots:
        hour_counts[slot.hour] += 1

    print("=" * 60)
    print("Flight Schedule Distribution — 210 Departures")
    print("=" * 60)
    print()
    print(f"{'Hour':>6}  {'Count':>5}  {'Bar'}")
    print("-" * 60)

    total = 0
    for hour in range(0, 24):
        count = hour_counts.get(hour, 0)
        total += count
        bar = "█" * count
        indicator = ""
        if hour in (7, 8):
            indicator = " ← morning peak"
        elif hour in (17, 18):
            indicator = " ← evening peak"
        print(f"{hour:02d}:00  {count:>5}  {bar}{indicator}")

    print("-" * 60)
    print(f"{'Total':>6}  {total:>5}")
    print()

    # Verify constraints
    first_flight_hour = min(s.hour for s in slots)
    last_flight_hour = max(s.hour for s in slots)

    morning_peak = sum(hour_counts.get(h, 0) for h in [7, 8])
    evening_peak = sum(hour_counts.get(h, 0) for h in [17, 18])
    midday = sum(hour_counts.get(h, 0) for h in range(9, 17))

    print("Validation checks:")
    print(f"  First flight hour: {first_flight_hour:02d}:00 (expect 05:00) {'✓' if first_flight_hour >= 5 else '✗'}")
    print(f"  Last flight hour:  {last_flight_hour:02d}:00 (expect 22:00) {'✓' if last_flight_hour <= 22 else '✗'}")
    print(f"  Morning peak (07-08): {morning_peak} flights {'✓' if morning_peak >= 25 else '✗'}")
    print(f"  Evening peak (17-18): {evening_peak} flights {'✓' if evening_peak >= 25 else '✗'}")
    print(f"  Mid-day (09-16): {midday} flights (expect steady flow) {'✓' if midday >= 60 else '✗'}")
    print(f"  Total: {total} {'✓' if total == 210 else '✗'}")
    print()

    # Arrivals distribution (paired 90 min before departure)
    arr_hours: Counter[int] = Counter()
    for slot in slots:
        arr = slot - timedelta(minutes=90)
        if arr.hour < 4:
            arr = arr.replace(hour=4, minute=0)
        arr_hours[arr.hour] += 1

    print("Paired Arrivals Distribution:")
    print(f"{'Hour':>6}  {'Count':>5}  {'Bar'}")
    print("-" * 60)
    for hour in range(0, 24):
        count = arr_hours.get(hour, 0)
        if count > 0:
            bar = "▓" * count
            print(f"{hour:02d}:00  {count:>5}  {bar}")
    print()


if __name__ == "__main__":
    main()
