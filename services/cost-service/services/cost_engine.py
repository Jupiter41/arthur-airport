"""Cost and revenue calculation engines.

Computes costs based on Kafka events and writes CostRecord nodes to Neo4j.
Sources: Eurocontrol Standard Inputs, EU Regulation 261/2004, ACI Airport Charges Report.
"""

from collections import defaultdict, deque
from copy import deepcopy
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
    "sim_day": 1,
}

# Track holding costs per flight to batch writes (every 5 sim-min)
_holding_accum: dict[str, dict] = {}

# Track last staffing cost hour to avoid duplicates
_last_staffing_hour: int = -1

# Track gate occupancy windows by flight_id → sim_time str (ISO 8601)
# Restart-safe: any flight whose start was missed is silently dropped on exit.
_gate_occupancy_starts: dict[str, str] = {}

# Rolling history of *completed* sim-days, used by recommendations.py for
# 95% confidence intervals. Keyed by signal name (category) → deque of daily
# totals; max 7 entries (last 7 sim-days).
_DAILY_HISTORY_MAX = 7
_daily_history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=_DAILY_HISTORY_MAX))


def get_daily_history() -> dict[str, list[float]]:
    """Return a copy of the rolling per-signal daily history (last 7 days)."""
    return {k: list(v) for k, v in _daily_history.items()}


def reset_daily_history() -> None:
    """Test helper — clear rolling history."""
    _daily_history.clear()


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
    _running_totals["sim_day"] = totals.get("sim_day", 1)
    for cat, val in totals.get("by_category", {}).items():
        _running_totals["by_category"][cat] = val


def reset_for_new_day(new_day: int) -> None:
    """Reset running totals when a new sim day starts (midnight boundary).

    Before clearing, snapshot the closing day's totals into the rolling history
    used by `recommendations.py` to compute 95% confidence intervals.
    """
    global _last_staffing_hour
    logger.info("day transition — resetting running totals", old_day=_running_totals["sim_day"], new_day=new_day)

    # Snapshot previous day's signals before zeroing.
    _daily_history["total_cost_eur"].append(float(_running_totals["total_cost_eur"]))
    _daily_history["total_revenue_eur"].append(float(_running_totals["total_revenue_eur"]))
    _daily_history["eu261_exposure"].append(float(_running_totals["eu261_exposure"]))
    for cat, val in _running_totals["by_category"].items():
        _daily_history[f"by_category.{cat}"].append(float(val))

    _running_totals["total_cost_eur"] = 0.0
    _running_totals["total_revenue_eur"] = 0.0
    _running_totals["net_eur"] = 0.0
    _running_totals["by_category"] = defaultdict(float)
    _running_totals["eu261_exposure"] = 0.0
    _running_totals["sim_day"] = new_day
    _last_staffing_hour = -1


def _record_cost(amount: float, category: str, is_revenue: bool = False, *, sim_time: str | None = None, sim_day: int | None = None) -> None:
    """Update in-memory running totals. Resets when sim_day changes."""
    # Day transition: reset running totals for the new day
    if sim_day is not None and sim_day != _running_totals["sim_day"]:
        reset_for_new_day(sim_day)

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


def _airline_code_from_flight_number(flight_number: str | None) -> str | None:
    """Extract the IATA carrier code from a flight number (e.g. 'AF1234' → 'AF').

    Falls back to ``None`` when the prefix is missing or malformed so the caller
    can use the base rate table.
    """
    if not flight_number:
        return None
    prefix = "".join(c for c in flight_number[:3] if c.isalpha()).upper()
    return prefix if 2 <= len(prefix) <= 3 else None


def resolve_rates_for_airline(rates: dict, airline_code: str | None) -> dict:
    """Return a rate dict with per-airline overrides applied on top of the base.

    Overrides live under ``rates["airline_overrides"][CODE]`` and are deep-merged
    so an airline can tune just one leaf field (e.g. only the passenger fee).
    When no override exists the base ``rates`` dict is returned **unchanged** —
    callers must not mutate it.
    """
    if not airline_code:
        return rates
    overrides = rates.get("airline_overrides", {}).get(airline_code)
    if not overrides:
        return rates

    merged = deepcopy(rates)

    def _merge(base: dict, patch: dict) -> None:
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                _merge(base[k], v)
            else:
                base[k] = v

    _merge(merged, overrides)
    return merged


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
    _record_cost(record["amount_eur"], record["category"], record["is_revenue"], sim_time=record.get("sim_time"), sim_day=record.get("sim_day"))

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
    flight_number = flight.get("flight_number", "")

    # Per-airline rate overrides resolved once per event (cheap deepcopy only
    # when an override exists for this carrier).
    airline_code = _airline_code_from_flight_number(flight_number)
    eff_rates = resolve_rates_for_airline(rates, airline_code)

    # Gate occupancy tracking — open window
    if direction == "departure" and new_status == "boarding":
        _gate_occupancy_starts.setdefault(flight_id, sim_time)
    elif direction == "arrival" and new_status == "at_gate":
        _gate_occupancy_starts.setdefault(flight_id, sim_time)

    # Gate occupancy tracking — close window + emit gate fee (dual entry)
    if (direction == "departure" and new_status == "departed") or (
        direction == "arrival" and new_status == "arrived"
    ):
        start = _gate_occupancy_starts.pop(flight_id, None)
        if start:
            try:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(sim_time.replace("Z", "+00:00"))
                delta_min = max(0, int((end_dt - start_dt).total_seconds() // 60))
            except (ValueError, AttributeError):
                delta_min = 0
            if delta_min > 0:
                gate_fee = compute_gate_fee(delta_min, eff_rates)
                if gate_fee > 0:
                    await _write_and_emit(
                        {
                            "id": str(uuid4()),
                            "category": "gate_fee",
                            "amount_eur": gate_fee,
                            "sim_time": sim_time,
                            "sim_day": sim_day,
                            "description": (
                                f"Gate fee — {flight_number} "
                                f"({delta_min} min occupancy)"
                            ),
                            "is_revenue": False,
                        },
                        flight_id=flight_id,
                    )
                    await _write_and_emit(
                        {
                            "id": str(uuid4()),
                            "category": "gate_fee",
                            "amount_eur": gate_fee,
                            "sim_time": sim_time,
                            "sim_day": sim_day,
                            "description": f"Gate fee revenue — {flight_number}",
                            "is_revenue": True,
                        },
                        flight_id=flight_id,
                    )

    # Cancellation drops any pending gate-occupancy window.
    if new_status == "cancelled":
        _gate_occupancy_starts.pop(flight_id, None)

    # Landing fee on arrival at gate
    if new_status == "at_gate" and direction == "arrival":
        fee = compute_landing_fee(aircraft_type, eff_rates)
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
        bags_per_pax = eff_rates.get("operations", {}).get("bags_per_pax", 1.2)
        bag_count = int(pax_count * bags_per_pax)
        handling = compute_ground_handling(aircraft_type, bag_count, eff_rates)
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
        pax_fee = compute_passenger_fee(pax_count, eff_rates)
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
        slot_fee = eff_rates["revenue"]["slot_fee_eur"]
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
        amount, desc = compute_eu261(delay_minutes, distance_km, pax_count, eff_rates)
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

    # Resolve per-airline overrides (matters for EU261 if a carrier negotiates
    # a different settlement schedule; otherwise no-op).
    airline_code = _airline_code_from_flight_number(flight.get("flight_number"))
    eff_rates = resolve_rates_for_airline(rates, airline_code)

    # Cancellation also clears any in-flight gate occupancy window.
    _gate_occupancy_starts.pop(flight_id, None)

    # Cancellations always trigger EU261 at max tier
    for tier in sorted(eff_rates["eu261"], key=lambda t: t.get("compensation_eur", 0), reverse=True):
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

    ops = rates.get("operations", {})
    peak_hours = set(ops.get("peak_hours", list(range(6, 23))))
    peak_cfg = ops.get("peak", {})
    off_cfg = ops.get("off_peak", {})

    if current_hour != _last_staffing_hour and current_hour >= 0:
        _last_staffing_hour = current_hour
        # Estimate open resources based on time of day
        cfg = peak_cfg if current_hour in peak_hours else off_cfg
        security_lanes = cfg.get("security_lanes_open", 3)
        boarding_flights = cfg.get("boarding_flights", 2)
        checkin_desks = cfg.get("checkin_desks_open", 4)

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
        cfg = peak_cfg if current_hour in peak_hours else off_cfg
        airside_pax = cfg.get("airside_pax", 300)
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
