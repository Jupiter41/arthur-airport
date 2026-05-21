"""Cost and revenue calculation engines.

Computes costs based on Kafka events and writes CostRecord nodes to Neo4j.
Sources: Eurocontrol Standard Inputs, EU Regulation 261/2004, ACI Airport Charges Report.
"""

from collections import defaultdict
from datetime import datetime
from uuid import uuid4

import structlog

from db.neo4j import (
    get_flight_info,
    get_holding_flights,
    link_cost_to_airport_day,
    link_cost_to_flight,
    link_cost_to_incident,
    link_cost_to_terminal,
    write_cost_record,
)
from kafka.producer import emit_cost_recorded

logger = structlog.get_logger(__name__)

WIDE_BODY_TYPES = {"B77W", "A333", "A332", "A359"}
REGIONAL_TYPES = {"DH8D", "E195", "AT75"}

# In-memory running totals — rebuilt from Neo4j on restart
_running_totals: dict = {
    "total_cost_eur": 0.0,
    "total_revenue_eur": 0.0,
    "net_eur": 0.0,
    "by_category": defaultdict(float),
    "eu261_exposure": 0.0,
    "last_updated": None,
}

# Track holding costs per flight to batch writes (every 5 sim-min)
_holding_accum: dict[str, dict] = {}

# Track last staffing cost hour to avoid duplicates
_last_staffing_hour: int = -1


def get_running_totals() -> dict:
    """Return the current running totals for the REST API."""
    totals = dict(_running_totals)
    totals["by_category"] = dict(totals["by_category"])
    return totals


def init_running_totals(totals: dict) -> None:
    """Restore running totals from Neo4j on restart."""
    _running_totals["total_cost_eur"] = totals.get("total_cost_eur", 0.0)
    _running_totals["total_revenue_eur"] = totals.get("total_revenue_eur", 0.0)
    _running_totals["net_eur"] = totals.get("net_eur", 0.0)
    for cat, val in totals.get("by_category", {}).items():
        _running_totals["by_category"][cat] = val


def _record_cost(amount: float, category: str, is_revenue: bool = False, *, sim_time: str | None = None) -> None:
    """Update in-memory running totals."""
    if is_revenue:
        _running_totals["total_revenue_eur"] += amount
    else:
        _running_totals["total_cost_eur"] += amount
        _running_totals["by_category"][category] += amount
    if category == "eu261_compensation" and not is_revenue:
        _running_totals["eu261_exposure"] += amount
    _running_totals["net_eur"] = (
        _running_totals["total_revenue_eur"] - _running_totals["total_cost_eur"]
    )
    _running_totals["last_updated"] = sim_time or _running_totals["last_updated"]


def _aircraft_family(aircraft_type: str) -> str:
    if aircraft_type in WIDE_BODY_TYPES:
        return "wide"
    if aircraft_type in REGIONAL_TYPES:
        return "regional"
    return "narrow"


# ─── Phase 3: Cost calculators ──────────────────────────────────


def compute_landing_fee(aircraft_type: str, rates: dict) -> float:
    mtow = rates["mtow_kg"].get(aircraft_type, 78_000)
    rate = rates["airport_fees"]["landing_rate_per_tonne_eur"]
    return round(rate * (mtow / 1_000), 2)


def compute_passenger_fee(pax_count: int, rates: dict) -> float:
    return round(pax_count * rates["airport_fees"]["passenger_departure_fee_eur"], 2)


def compute_gate_fee(gate_occupancy_minutes: int, rates: dict) -> float:
    hours = gate_occupancy_minutes / 60
    return round(hours * rates["airport_fees"]["gate_rate_per_hour_eur"], 2)


def compute_eu261(
    delay_minutes: int,
    distance_km: float,
    pax_count: int,
    rates: dict,
) -> tuple[float, str]:
    if delay_minutes < 180:
        return 0.0, "below EU261 threshold"

    for tier in sorted(rates["eu261"], key=lambda t: t["min_delay_minutes"], reverse=True):
        if (
            delay_minutes >= tier["min_delay_minutes"]
            and distance_km <= tier["max_distance_km"]
            and not tier.get("assistance_only", False)
        ):
            amount = tier["compensation_eur"] * pax_count
            desc = (
                f"EU261 — {pax_count} pax × €{tier['compensation_eur']} "
                f"({distance_km:.0f} km, delay {delay_minutes}min)"
            )
            return round(amount, 2), desc
    return 0.0, "EU261 not applicable"


def compute_holding_cost_per_tick(
    aircraft_type: str,
    delta_minutes: int,
    rates: dict,
) -> float:
    family = _aircraft_family(aircraft_type)
    burn_per_hour = rates["delay_costs"]["holding_burn_kg_per_hour"][family]
    burn_per_min = burn_per_hour / 60
    price = rates["delay_costs"]["fuel_price_per_kg_eur"]
    return round(burn_per_min * delta_minutes * price, 2)


def compute_ground_handling(
    aircraft_type: str,
    bag_count: int,
    rates: dict,
) -> dict[str, float]:
    r = rates["ground_handling"]
    is_wide = aircraft_type in WIDE_BODY_TYPES
    return {
        "pushback": r["pushback_eur"],
        "catering": r["catering_wide_eur"] if is_wide else r["catering_narrow_eur"],
        "cleaning": r["cleaning_wide_eur"] if is_wide else r["cleaning_narrow_eur"],
        "jetbridge": r["jetbridge_eur"],
        "baggage_loading": round(bag_count * r["baggage_loader_per_bag_eur"], 2),
    }


def compute_incident_direct_cost(incident_type: str, rates: dict) -> float:
    entry = rates["incident_costs"].get(incident_type)
    if entry is None:
        return 0.0
    return entry["direct_eur"]


def compute_incident_response_cost(
    incident_type: str,
    ttr_minutes: int,
    rates: dict,
) -> float:
    entry = rates["incident_costs"].get(incident_type)
    if entry is None:
        return 0.0
    base = entry["response_eur"]
    extra_periods = max(0, (ttr_minutes - 30) // 15)
    return round(base * (1 + extra_periods * 0.25), 2)


def compute_staffing_cost_per_hour(
    security_lanes_open: int,
    active_flights_boarding: int,
    checkin_desks_open: int,
    rates: dict,
) -> dict[str, float]:
    r = rates["staffing"]
    return {
        "security": security_lanes_open * r["security_officer_per_hour_eur"],
        "checkin": checkin_desks_open * r["checkin_agent_per_hour_eur"],
        "gate": active_flights_boarding * r["gate_agent_per_hour_eur"],
    }


# ─── Phase 4: Revenue calculators ──────────────────────────────


def compute_retail_revenue_per_tick(
    airside_pax_count: int,
    delta_minutes: int,
    rates: dict,
) -> float:
    hourly_rate = rates["revenue"]["retail_spend_per_pax_per_hour_airside_eur"]
    return round(airside_pax_count * hourly_rate * (delta_minutes / 60), 2)


# ─── Event handlers ─────────────────────────────────────────────


MAX_SINGLE_COST_EUR = 1_000_000  # sanity guard — no single record should exceed €1M


async def _write_and_emit(
    record: dict,
    flight_id: str | None = None,
    incident_id: str | None = None,
    terminal_id: str | None = None,
) -> None:
    """Write CostRecord to Neo4j, link relationships, update totals, emit Kafka event."""
    amount = record["amount_eur"]
    if abs(amount) > MAX_SINGLE_COST_EUR:
        logger.warning(
            "cost record exceeds sanity limit — skipped",
            category=record["category"],
            amount_eur=amount,
            limit=MAX_SINGLE_COST_EUR,
        )
        return

    await write_cost_record(record)
    _record_cost(record["amount_eur"], record["category"], record["is_revenue"], sim_time=record.get("sim_time"))

    if flight_id:
        await link_cost_to_flight(record["id"], flight_id)
    if incident_id:
        await link_cost_to_incident(record["id"], incident_id)
    if terminal_id:
        await link_cost_to_terminal(record["id"], terminal_id)

    await link_cost_to_airport_day(record["id"], record["sim_day"])

    emit_cost_recorded(
        cost_record_id=record["id"],
        category=record["category"],
        amount_eur=record["amount_eur"],
        is_revenue=record["is_revenue"],
        sim_time=record["sim_time"],
        sim_day=record["sim_day"],
        description=record["description"],
        flight_id=flight_id,
        incident_id=incident_id,
    )


async def on_flight_status_changed(payload: dict, sim_time: str, sim_day: int, rates: dict) -> None:
    """Handle FlightStatusChanged — trigger cost calculations."""
    flight_id = payload.get("flight_id")
    new_status = payload.get("new_status") or payload.get("status")
    if not flight_id or not new_status:
        return

    flight = await get_flight_info(flight_id)
    if not flight:
        return

    aircraft_type = flight.get("aircraft_type", "A320")
    pax_count = flight.get("pax_count", 0)
    direction = flight.get("direction", "departure")

    # Landing fee on arrival at gate
    if new_status == "at_gate" and direction == "arrival":
        fee = compute_landing_fee(aircraft_type, rates)
        # Cost to airline
        await _write_and_emit(
            {
                "id": str(uuid4()),
                "category": "landing_fee",
                "amount_eur": fee,
                "sim_time": sim_time,
                "sim_day": sim_day,
                "description": f"Landing fee — {flight.get('flight_number', '')} ({aircraft_type})",
                "is_revenue": False,
            },
            flight_id=flight_id,
        )
        # Revenue to airport
        await _write_and_emit(
            {
                "id": str(uuid4()),
                "category": "landing_fee",
                "amount_eur": fee,
                "sim_time": sim_time,
                "sim_day": sim_day,
                "description": f"Landing fee revenue — {flight.get('flight_number', '')}",
                "is_revenue": True,
            },
            flight_id=flight_id,
        )

        # Ground handling costs
        bag_count = int(pax_count * 1.2)  # estimate 1.2 bags per pax
        handling = compute_ground_handling(aircraft_type, bag_count, rates)
        for item_name, amount in handling.items():
            await _write_and_emit(
                {
                    "id": str(uuid4()),
                    "category": "ground_handling",
                    "amount_eur": amount,
                    "sim_time": sim_time,
                    "sim_day": sim_day,
                    "description": f"Ground handling ({item_name}) — {flight.get('flight_number', '')}",
                    "is_revenue": False,
                },
                flight_id=flight_id,
            )

    # Passenger fee on departure
    if new_status == "departed" and direction == "departure":
        pax_fee = compute_passenger_fee(pax_count, rates)
        await _write_and_emit(
            {
                "id": str(uuid4()),
                "category": "passenger_fee",
                "amount_eur": pax_fee,
                "sim_time": sim_time,
                "sim_day": sim_day,
                "description": f"Passenger departure fee — {pax_count} pax on {flight.get('flight_number', '')}",
                "is_revenue": False,
            },
            flight_id=flight_id,
        )
        # Revenue side
        await _write_and_emit(
            {
                "id": str(uuid4()),
                "category": "passenger_fee",
                "amount_eur": pax_fee,
                "sim_time": sim_time,
                "sim_day": sim_day,
                "description": f"Passenger fee revenue — {flight.get('flight_number', '')}",
                "is_revenue": True,
            },
            flight_id=flight_id,
        )
        # Slot revenue
        slot_fee = rates["revenue"]["slot_fee_eur"]
        await _write_and_emit(
            {
                "id": str(uuid4()),
                "category": "slot_revenue",
                "amount_eur": slot_fee,
                "sim_time": sim_time,
                "sim_day": sim_day,
                "description": f"Slot fee — {flight.get('flight_number', '')}",
                "is_revenue": True,
            },
            flight_id=flight_id,
        )

    # EU261 on delay >= 180 min
    delay_minutes = payload.get("delay_minutes", 0) or flight.get("delay_minutes", 0)
    if new_status == "delayed" and delay_minutes >= 180:
        distance_km = flight.get("distance_km") or 2000.0
        amount, desc = compute_eu261(delay_minutes, distance_km, pax_count, rates)
        if amount > 0:
            await _write_and_emit(
                {
                    "id": str(uuid4()),
                    "category": "eu261_compensation",
                    "amount_eur": amount,
                    "sim_time": sim_time,
                    "sim_day": sim_day,
                    "description": desc,
                    "is_revenue": False,
                },
                flight_id=flight_id,
            )


async def on_flight_cancelled(payload: dict, sim_time: str, sim_day: int, rates: dict) -> None:
    """Handle FlightCancelled — always triggers EU261."""
    flight_id = payload.get("flight_id")
    if not flight_id:
        return

    flight = await get_flight_info(flight_id)
    if not flight:
        return

    pax_count = flight.get("pax_count", 0)
    distance_km = flight.get("distance_km") or 2000.0

    # Cancellations always trigger EU261 at max tier
    for tier in sorted(rates["eu261"], key=lambda t: t.get("compensation_eur", 0), reverse=True):
        if not tier.get("assistance_only", False) and distance_km <= tier["max_distance_km"]:
            amount = tier["compensation_eur"] * pax_count
            desc = (
                f"EU261 (cancellation) — {pax_count} pax × €{tier['compensation_eur']} "
                f"({distance_km:.0f} km)"
            )
            await _write_and_emit(
                {
                    "id": str(uuid4()),
                    "category": "eu261_compensation",
                    "amount_eur": round(amount, 2),
                    "sim_time": sim_time,
                    "sim_day": sim_day,
                    "description": desc,
                    "is_revenue": False,
                },
                flight_id=flight_id,
            )
            break


async def on_incident_created(payload: dict, sim_time: str, sim_day: int, rates: dict) -> None:
    """Handle IncidentCreated — compute direct costs."""
    incident_id = payload.get("incident_id") or payload.get("id")
    incident_type = payload.get("type", "system_failure")
    if not incident_id:
        return

    direct_cost = compute_incident_direct_cost(incident_type, rates)
    if direct_cost > 0:
        await _write_and_emit(
            {
                "id": str(uuid4()),
                "category": "incident_direct",
                "amount_eur": direct_cost,
                "sim_time": sim_time,
                "sim_day": sim_day,
                "description": f"Incident direct cost — {incident_type}",
                "is_revenue": False,
            },
            incident_id=incident_id,
        )


async def on_incident_resolved(payload: dict, sim_time: str, sim_day: int, rates: dict) -> None:
    """Handle IncidentStatusChanged (resolved) — compute response costs."""
    incident_id = payload.get("incident_id") or payload.get("id")
    new_status = payload.get("new_status") or payload.get("status")
    if not incident_id or new_status != "resolved":
        return

    incident_type = payload.get("type", "system_failure")
    ttr_minutes = payload.get("ttr_minutes", 30)

    response_cost = compute_incident_response_cost(incident_type, ttr_minutes, rates)
    if response_cost > 0:
        await _write_and_emit(
            {
                "id": str(uuid4()),
                "category": "incident_response",
                "amount_eur": response_cost,
                "sim_time": sim_time,
                "sim_day": sim_day,
                "description": f"Incident response cost — {incident_type} ({ttr_minutes}min TTR)",
                "is_revenue": False,
            },
            incident_id=incident_id,
        )


async def on_clock_tick(payload: dict, sim_time: str, sim_day: int, rates: dict) -> None:
    """Handle SimClockTick — accumulate holding fuel, staffing, and retail revenue."""
    global _last_staffing_hour

    tick_number = payload.get("tick_number", 0)

    # Holding fuel — check every tick but batch-write every 5 sim-min
    if tick_number % 5 == 0:
        holding_flights = await get_holding_flights()
        for f in holding_flights:
            fid = f["id"]
            aircraft_type = f.get("aircraft_type", "A320")
            cost = compute_holding_cost_per_tick(aircraft_type, 5, rates)
            if cost > 0:
                await _write_and_emit(
                    {
                        "id": str(uuid4()),
                        "category": "holding_fuel",
                        "amount_eur": cost,
                        "sim_time": sim_time,
                        "sim_day": sim_day,
                        "description": f"Holding fuel — {f.get('flight_number', '')} (5 min)",
                        "is_revenue": False,
                    },
                    flight_id=fid,
                )

    # Staffing costs — once per simulated hour
    try:
        st = datetime.fromisoformat(sim_time.replace("Z", "+00:00"))
        current_hour = st.hour
    except (ValueError, AttributeError):
        current_hour = -1

    if current_hour != _last_staffing_hour and current_hour >= 0:
        _last_staffing_hour = current_hour
        # Estimate open resources based on time of day
        is_peak = 6 <= current_hour <= 22
        security_lanes = 8 if is_peak else 3
        boarding_flights = 10 if is_peak else 2
        checkin_desks = 12 if is_peak else 4

        staffing = compute_staffing_cost_per_hour(
            security_lanes, boarding_flights, checkin_desks, rates,
        )
        for staff_type, cost in staffing.items():
            if cost > 0:
                await _write_and_emit(
                    {
                        "id": str(uuid4()),
                        "category": "staffing",
                        "amount_eur": cost,
                        "sim_time": sim_time,
                        "sim_day": sim_day,
                        "description": f"Staffing ({staff_type}) — hour {current_hour:02d}:00",
                        "is_revenue": False,
                    },
                )

    # Retail revenue — accumulate every 10 sim-minutes
    if tick_number % 10 == 0:
        # Estimate airside pax from time of day
        is_peak = 6 <= current_hour <= 22
        airside_pax = 2000 if is_peak else 300
        rev = compute_retail_revenue_per_tick(airside_pax, 10, rates)
        if rev > 0:
            await _write_and_emit(
                {
                    "id": str(uuid4()),
                    "category": "retail_revenue",
                    "amount_eur": rev,
                    "sim_time": sim_time,
                    "sim_day": sim_day,
                    "description": f"Retail revenue — {airside_pax} pax airside (10 min)",
                    "is_revenue": True,
                },
            )
