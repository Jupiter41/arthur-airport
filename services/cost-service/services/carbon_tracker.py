"""Carbon footprint tracker for cost-service.

Source attribution:
- ICAO Carbon Emissions Calculator methodology (per-pax-km factors)
- ICAO Doc 9889 / EEDB (APU emission rates)
- ACI Airport Carbon Accreditation (terminal energy benchmarks)
- IPCC AR6 + EEA 2023 (grid intensity)

All inputs are public reference data. CarbonRecord nodes are written to Neo4j
and a `CarbonRecorded` event is emitted on `cost.events` for each record.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import uuid4

import structlog

from db.neo4j import (
    link_carbon_to_airport_day,
    link_carbon_to_flight,
    link_carbon_to_terminal,
    rebuild_carbon_totals,
    write_carbon_record,
)
from kafka.producer import emit_carbon_recorded

logger = structlog.get_logger(__name__)

WIDE_BODY_TYPES = {"B77W", "A333", "A332", "A359", "B748", "A380"}
REGIONAL_TYPES = {"DH8D", "E195", "AT75"}


def _aircraft_family(aircraft_type: str) -> str:
    if aircraft_type in WIDE_BODY_TYPES:
        return "wide"
    if aircraft_type in REGIONAL_TYPES:
        return "regional"
    return "narrow"


# In-memory running totals — rebuilt from Neo4j on restart
_carbon_totals: dict = {
    "total_kg": 0.0,
    "by_source": defaultdict(float),
    "sim_day": 1,
    "last_updated": None,
}


def get_carbon_totals() -> dict:
    return {
        "total_kg": round(_carbon_totals["total_kg"], 2),
        "by_source": {k: round(v, 2) for k, v in _carbon_totals["by_source"].items()},
        "sim_day": _carbon_totals["sim_day"],
        "last_updated": _carbon_totals["last_updated"],
    }


def init_carbon_totals(totals: dict) -> None:
    _carbon_totals["total_kg"] = totals.get("total_kg", 0.0)
    _carbon_totals["sim_day"] = totals.get("sim_day", 1)
    _carbon_totals["by_source"] = defaultdict(float)
    for k, v in totals.get("by_source", {}).items():
        _carbon_totals["by_source"][k] = v


def reset_for_new_day(new_day: int) -> None:
    logger.info("carbon — day transition reset", old=_carbon_totals["sim_day"], new=new_day)
    _carbon_totals["total_kg"] = 0.0
    _carbon_totals["by_source"] = defaultdict(float)
    _carbon_totals["sim_day"] = new_day


def _accumulate(source: str, kg: float, sim_time: str | None, sim_day: int | None) -> None:
    if sim_day is not None and sim_day != _carbon_totals["sim_day"]:
        reset_for_new_day(sim_day)
    _carbon_totals["total_kg"] += kg
    _carbon_totals["by_source"][source] += kg
    _carbon_totals["last_updated"] = sim_time or _carbon_totals["last_updated"]


# ─── Calculators ──────────────────────────────────────────────


def compute_flight_emissions(distance_km: float, pax_count: int, factors: dict) -> float:
    """Scope 3 flight emissions per ICAO methodology.

    distance_km × pax × per-pax-km factor (with band lookup).
    """
    f = factors["flight"]
    if distance_km <= f["short_haul_max_km"]:
        ef = f["short_haul_kg_per_pax_km"]
    elif distance_km <= f["medium_haul_max_km"]:
        ef = f["medium_haul_kg_per_pax_km"]
    else:
        ef = f["long_haul_kg_per_pax_km"]
    return round(max(0.0, distance_km * max(0, pax_count) * ef), 2)


def compute_apu_emissions(aircraft_type: str, stand_minutes: int, factors: dict) -> float:
    family = _aircraft_family(aircraft_type)
    rate = factors["apu"]["kg_per_minute"].get(family, 3.0)
    return round(max(0.0, stand_minutes * rate), 2)


def compute_terminal_emissions(airside_pax: int, minutes: int, factors: dict) -> float:
    t = factors["terminal"]
    kwh = airside_pax * t["kwh_per_pax_per_hour"] * (minutes / 60.0)
    return round(max(0.0, kwh * t["grid_kg_per_kwh"]), 2)


def compute_ground_vehicle_emissions(factors: dict) -> float:
    return round(factors["ground_vehicle"]["kg_per_turnaround"], 2)


# ─── Persistence helpers ──────────────────────────────────────


async def _persist(
    *,
    source: str,
    co2_kg: float,
    sim_time: str,
    sim_day: int,
    description: str,
    flight_id: str | None = None,
    terminal_id: str | None = None,
) -> None:
    if co2_kg <= 0:
        return
    record = {
        "id": str(uuid4()),
        "source": source,
        "co2_kg": co2_kg,
        "sim_time": sim_time,
        "sim_day": sim_day,
        "description": description,
        "flight_id": flight_id or "",
    }
    await write_carbon_record(record)
    if flight_id:
        await link_carbon_to_flight(record["id"], flight_id)
    if terminal_id:
        await link_carbon_to_terminal(record["id"], terminal_id)
    await link_carbon_to_airport_day(record["id"], sim_day)
    _accumulate(source, co2_kg, sim_time, sim_day)
    emit_carbon_recorded(
        record_id=record["id"],
        source=source,
        co2_kg=co2_kg,
        sim_time=sim_time,
        sim_day=sim_day,
        description=description,
        flight_id=flight_id,
    )


# ─── Event handlers ───────────────────────────────────────────


async def on_flight_departed(
    flight: dict, sim_time: str, sim_day: int, factors: dict
) -> None:
    """Emit flight + APU + ground-vehicle carbon at departure."""
    flight_id = flight.get("id")
    if not flight_id:
        return
    aircraft_type = flight.get("aircraft_type", "A320")
    pax_count = flight.get("pax_count", 0) or 0
    distance_km = flight.get("distance_km") or 0.0

    flight_kg = compute_flight_emissions(distance_km, pax_count, factors)
    await _persist(
        source="flight",
        co2_kg=flight_kg,
        sim_time=sim_time,
        sim_day=sim_day,
        description=(
            f"Flight emissions — {flight.get('flight_number', '')} "
            f"({pax_count} pax × {distance_km:.0f} km)"
        ),
        flight_id=flight_id,
    )

    stand_minutes = factors["apu"].get("stand_minutes_default", 45)
    apu_kg = compute_apu_emissions(aircraft_type, stand_minutes, factors)
    await _persist(
        source="apu",
        co2_kg=apu_kg,
        sim_time=sim_time,
        sim_day=sim_day,
        description=(
            f"APU — {flight.get('flight_number', '')} "
            f"({aircraft_type}, {stand_minutes} min)"
        ),
        flight_id=flight_id,
    )

    gv_kg = compute_ground_vehicle_emissions(factors)
    await _persist(
        source="ground_vehicle",
        co2_kg=gv_kg,
        sim_time=sim_time,
        sim_day=sim_day,
        description=f"Ground service vehicles — {flight.get('flight_number', '')}",
        flight_id=flight_id,
    )


async def on_clock_tick(
    payload: dict, sim_time: str, sim_day: int, factors: dict, rates: dict
) -> None:
    """Terminal energy emissions every 10 sim-min using estimated airside pax."""
    tick_number = payload.get("tick_number", 0)
    if tick_number % 10 != 0:
        return

    try:
        st = datetime.fromisoformat(sim_time.replace("Z", "+00:00"))
        hour = st.hour
    except (ValueError, AttributeError):
        hour = 12

    ops = rates.get("operations", {})
    peak_hours = set(ops.get("peak_hours", list(range(6, 23))))
    cfg = ops.get("peak", {}) if hour in peak_hours else ops.get("off_peak", {})
    airside_pax = cfg.get("airside_pax", 300)

    kg = compute_terminal_emissions(airside_pax, 10, factors)
    await _persist(
        source="terminal",
        co2_kg=kg,
        sim_time=sim_time,
        sim_day=sim_day,
        description=f"Terminal energy — {airside_pax} airside pax (10 min)",
    )


async def restore_totals_from_db() -> None:
    totals = await rebuild_carbon_totals()
    if totals:
        init_carbon_totals(totals)
        logger.info(
            "carbon totals restored",
            total_kg=totals.get("total_kg", 0.0),
            sim_day=totals.get("sim_day", 1),
        )
