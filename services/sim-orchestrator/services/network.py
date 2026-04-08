"""Multi-airport network simulation (Phase 3).

Maintains lightweight virtual state for remote hub airports in the KART
network.  Propagates delays across airport pairs and models Ground Delay
Programs (GDP) without running a full simulation for each remote airport.

The module is entirely in-memory — remote airport state is not stored in
Neo4j.  KART remains the single source of truth; remote airports are
approximations used for cascade visualisation and GDP modelling.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ── Data models ──────────────────────────────────────────────────


@dataclass
class NetworkAirport:
    """Represents one airport in the network (home or remote hub)."""
    icao: str
    iata: str
    name: str
    lat: float
    lon: float
    role: str                       # "home" | "hub"
    turnaround_narrow_min: int
    turnaround_wide_min: int
    base_delay_minutes: int
    daily_movements: int

    # Mutable runtime state (not persisted)
    current_delay_minutes: float = 0.0
    gdp_active: bool = False
    gdp_start_time: datetime | None = None
    gdp_departure_rate_pct: float = 1.0  # 1.0 = normal, 0.5 = 50% rate
    disruption_level: str = "green"      # green / amber / red
    recovery_eta_minutes: float = 0.0
    active_incidents: int = 0


@dataclass
class DelayPropagation:
    """Record of a delay propagating between two airports."""
    source_icao: str
    target_icao: str
    flight_number: str
    original_delay_minutes: float
    propagated_delay_minutes: float
    sim_time: str
    cascade_depth: int


@dataclass
class NetworkGDP:
    """An active Ground Delay Program at a specific airport."""
    airport_icao: str
    start_time: str
    reason: str
    capacity_reduction_pct: float
    affected_feeder_airports: list[str]
    departure_rate_pct: float
    estimated_end_time: str | None = None


@dataclass
class PropagationConfig:
    min_propagation_delay: int = 15
    max_cascade_depth: int = 3
    absorption_factor: float = 0.6
    recovery_rate_per_hour: float = 5.0


@dataclass
class GDPConfig:
    capacity_trigger_threshold: float = 0.60
    max_departure_rate_reduction: float = 0.50
    min_duration_minutes: int = 60
    cooldown_minutes: int = 120


@dataclass
class NetworkConfig:
    enabled: bool
    name: str
    home: str
    airports: list[NetworkAirport]
    propagation: PropagationConfig
    gdp: GDPConfig


# ── Configuration loader ─────────────────────────────────────────


def load_network_config(path: str | Path | None = None) -> NetworkConfig:
    """Load network.yaml and return a typed config object."""
    if path is None:
        # Docker: /app/config/network.yaml, local: config/network.yaml
        candidates = [
            Path("/app/config/network.yaml"),
            Path("config/network.yaml"),
            Path(__file__).resolve().parents[2] / "config" / "network.yaml",
        ]
        for p in candidates:
            if p.exists():
                path = p
                break
    if path is None or not Path(path).exists():
        logger.warning("network.yaml not found — network simulation disabled")
        return NetworkConfig(
            enabled=False,
            name="",
            home="KART",
            airports=[],
            propagation=PropagationConfig(),
            gdp=GDPConfig(),
        )

    with open(path) as f:
        raw = yaml.safe_load(f)

    net = raw.get("network", {})
    airports = [
        NetworkAirport(**a)
        for a in net.get("airports", [])
    ]
    prop_raw = net.get("propagation", {})
    gdp_raw = net.get("gdp", {})

    return NetworkConfig(
        enabled=net.get("enabled", False),
        name=net.get("name", ""),
        home=net.get("home", "KART"),
        airports=airports,
        propagation=PropagationConfig(**prop_raw),
        gdp=GDPConfig(**gdp_raw),
    )


# ── Network engine ───────────────────────────────────────────────


class NetworkEngine:
    """Lightweight engine modelling cross-airport delay propagation.

    Does NOT run a full simulation for remote airports.  Instead:
    - Tracks current_delay_minutes per remote airport
    - Propagates KART outbound delays to destination airports
    - Propagates return delay back to KART inbound schedule
    - Models GDP when capacity drops
    """

    def __init__(self, config: NetworkConfig | None = None):
        if config is None:
            config = load_network_config()
        self.config = config
        self._airports: dict[str, NetworkAirport] = {
            a.icao: a for a in config.airports
        }
        self._propagation_log: list[DelayPropagation] = []
        self._active_gdps: dict[str, NetworkGDP] = {}
        self._gdp_cooldowns: dict[str, datetime] = {}
        self._rng = random.Random(42)
        self._sim_time: datetime | None = None

    @property
    def enabled(self) -> bool:
        return self.config.enabled and len(self.config.airports) > 1

    def get_airport(self, icao: str) -> NetworkAirport | None:
        return self._airports.get(icao)

    def get_all_airports(self) -> list[NetworkAirport]:
        return list(self._airports.values())

    # ── Tick processing ──────────────────────────────────────────

    def on_tick(self, sim_time: datetime) -> None:
        """Called every sim-minute.  Updates remote airport state."""
        if not self.enabled:
            return
        self._sim_time = sim_time

        # Recover remote airports toward baseline
        for airport in self._airports.values():
            if airport.role == "home":
                continue
            if airport.current_delay_minutes > airport.base_delay_minutes:
                recovery = self.config.propagation.recovery_rate_per_hour / 60.0
                airport.current_delay_minutes = max(
                    airport.base_delay_minutes,
                    airport.current_delay_minutes - recovery,
                )
            # Update disruption level
            airport.disruption_level = _compute_disruption_level(
                airport.current_delay_minutes
            )
            # Update recovery ETA
            if airport.current_delay_minutes > airport.base_delay_minutes:
                excess = airport.current_delay_minutes - airport.base_delay_minutes
                rate = self.config.propagation.recovery_rate_per_hour / 60.0
                airport.recovery_eta_minutes = excess / rate if rate > 0 else 999
            else:
                airport.recovery_eta_minutes = 0

        # Check GDP conditions for each airport
        self._evaluate_gdps(sim_time)

    # ── Delay propagation ────────────────────────────────────────

    def propagate_delay(
        self,
        flight_number: str,
        source_icao: str,
        target_icao: str,
        delay_minutes: float,
        cascade_depth: int = 0,
    ) -> float:
        """Propagate a flight delay from source to target airport.

        Returns the propagated delay at the target (after absorption).
        """
        if not self.enabled:
            return 0.0
        if delay_minutes < self.config.propagation.min_propagation_delay:
            return 0.0
        if cascade_depth >= self.config.propagation.max_cascade_depth:
            return 0.0

        target = self._airports.get(target_icao)
        if target is None or target.role == "home":
            # Delays arriving at home airport are handled by the flight-service FSM
            return 0.0

        # Compute propagated delay after turnaround absorption
        turnaround_buffer = target.turnaround_narrow_min
        absorbed = delay_minutes * self.config.propagation.absorption_factor
        propagated = max(0.0, delay_minutes - turnaround_buffer - absorbed)

        if propagated > 0:
            target.current_delay_minutes += propagated
            target.disruption_level = _compute_disruption_level(
                target.current_delay_minutes
            )

            record = DelayPropagation(
                source_icao=source_icao,
                target_icao=target_icao,
                flight_number=flight_number,
                original_delay_minutes=delay_minutes,
                propagated_delay_minutes=propagated,
                sim_time=self._sim_time.isoformat() if self._sim_time else "",
                cascade_depth=cascade_depth,
            )
            self._propagation_log.append(record)
            # Keep log bounded
            if len(self._propagation_log) > 1000:
                self._propagation_log = self._propagation_log[-500:]

            logger.info(
                "Network delay propagated: %s → %s via %s (%.0f min → %.0f min, depth=%d)",
                source_icao, target_icao, flight_number,
                delay_minutes, propagated, cascade_depth,
            )

        return propagated

    def get_return_delay(self, remote_icao: str) -> float:
        """Get the expected delay for flights returning from a remote airport to KART.

        This models the cascade-back effect: if LHR is delayed, flights
        from LHR to KART will be delayed too.
        """
        airport = self._airports.get(remote_icao)
        if airport is None:
            return 0.0
        excess = airport.current_delay_minutes - airport.base_delay_minutes
        return max(0.0, excess)

    # ── GDP management ───────────────────────────────────────────

    def _evaluate_gdps(self, sim_time: datetime) -> None:
        """Check if any airport should declare or lift a GDP."""
        for airport in self._airports.values():
            if airport.role == "home":
                continue

            icao = airport.icao

            # Check for GDP lift
            if icao in self._active_gdps:
                gdp = self._active_gdps[icao]
                if airport.disruption_level == "green":
                    logger.info("GDP lifted at %s", icao)
                    del self._active_gdps[icao]
                    airport.gdp_active = False
                    airport.gdp_departure_rate_pct = 1.0
                    self._gdp_cooldowns[icao] = sim_time
                continue

            # Check cooldown
            if icao in self._gdp_cooldowns:
                elapsed = (sim_time - self._gdp_cooldowns[icao]).total_seconds() / 60
                if elapsed < self.config.gdp.cooldown_minutes:
                    continue

            # Check if GDP should be declared
            if airport.disruption_level == "red":
                rate_pct = 1.0 - self.config.gdp.max_departure_rate_reduction
                feeders = [
                    a.icao for a in self._airports.values()
                    if a.icao != icao and a.role != "home"
                ]
                feeders.append(self.config.home)

                gdp = NetworkGDP(
                    airport_icao=icao,
                    start_time=sim_time.isoformat(),
                    reason=f"High disruption at {airport.name} (delay {airport.current_delay_minutes:.0f} min)",
                    capacity_reduction_pct=self.config.gdp.max_departure_rate_reduction,
                    affected_feeder_airports=feeders,
                    departure_rate_pct=rate_pct,
                )
                self._active_gdps[icao] = gdp
                airport.gdp_active = True
                airport.gdp_departure_rate_pct = rate_pct

                logger.info(
                    "GDP declared at %s — departure rate %.0f%%, feeders: %s",
                    icao, rate_pct * 100, feeders,
                )

    def declare_gdp(
        self,
        airport_icao: str,
        reason: str,
        capacity_reduction_pct: float = 0.50,
    ) -> NetworkGDP | None:
        """Manually declare a GDP at a specific airport."""
        airport = self._airports.get(airport_icao)
        if airport is None:
            return None

        feeders = [
            a.icao for a in self._airports.values()
            if a.icao != airport_icao
        ]
        rate_pct = 1.0 - capacity_reduction_pct
        gdp = NetworkGDP(
            airport_icao=airport_icao,
            start_time=self._sim_time.isoformat() if self._sim_time else "",
            reason=reason,
            capacity_reduction_pct=capacity_reduction_pct,
            affected_feeder_airports=feeders,
            departure_rate_pct=rate_pct,
        )
        self._active_gdps[airport_icao] = gdp
        airport.gdp_active = True
        airport.gdp_departure_rate_pct = rate_pct
        return gdp

    def lift_gdp(self, airport_icao: str) -> bool:
        """Manually lift a GDP."""
        if airport_icao not in self._active_gdps:
            return False
        del self._active_gdps[airport_icao]
        airport = self._airports.get(airport_icao)
        if airport:
            airport.gdp_active = False
            airport.gdp_departure_rate_pct = 1.0
        if self._sim_time:
            self._gdp_cooldowns[airport_icao] = self._sim_time
        return True

    def get_active_gdps(self) -> list[NetworkGDP]:
        return list(self._active_gdps.values())

    def is_feeder_constrained(self, feeder_icao: str) -> tuple[bool, float]:
        """Check if a feeder airport is constrained by any active GDP.

        Returns (is_constrained, departure_rate_pct) where departure_rate_pct
        is the most restrictive rate from all active GDPs affecting this feeder.
        """
        min_rate = 1.0
        constrained = False
        for gdp in self._active_gdps.values():
            if feeder_icao in gdp.affected_feeder_airports:
                constrained = True
                min_rate = min(min_rate, gdp.departure_rate_pct)
        return constrained, min_rate

    # ── Status / serialisation ───────────────────────────────────

    def get_network_status(self) -> dict[str, Any]:
        """Return full network status for the REST API."""
        return {
            "enabled": self.enabled,
            "name": self.config.name,
            "home": self.config.home,
            "airports": [
                {
                    "icao": a.icao,
                    "iata": a.iata,
                    "name": a.name,
                    "lat": a.lat,
                    "lon": a.lon,
                    "role": a.role,
                    "daily_movements": a.daily_movements,
                    "current_delay_minutes": round(a.current_delay_minutes, 1),
                    "disruption_level": a.disruption_level,
                    "gdp_active": a.gdp_active,
                    "gdp_departure_rate_pct": round(a.gdp_departure_rate_pct, 2),
                    "recovery_eta_minutes": round(a.recovery_eta_minutes, 1),
                    "active_incidents": a.active_incidents,
                }
                for a in self._airports.values()
            ],
            "active_gdps": [
                {
                    "airport_icao": g.airport_icao,
                    "start_time": g.start_time,
                    "reason": g.reason,
                    "capacity_reduction_pct": g.capacity_reduction_pct,
                    "affected_feeder_airports": g.affected_feeder_airports,
                    "departure_rate_pct": g.departure_rate_pct,
                    "estimated_end_time": g.estimated_end_time,
                }
                for g in self._active_gdps.values()
            ],
            "recent_propagations": [
                {
                    "source_icao": p.source_icao,
                    "target_icao": p.target_icao,
                    "flight_number": p.flight_number,
                    "original_delay_minutes": p.original_delay_minutes,
                    "propagated_delay_minutes": p.propagated_delay_minutes,
                    "sim_time": p.sim_time,
                    "cascade_depth": p.cascade_depth,
                }
                for p in self._propagation_log[-50:]
            ],
            "arcs": _build_network_arcs(self._airports, self._propagation_log),
        }

    def get_airport_pairs_for_map(self) -> list[dict]:
        """Return arc data for network map visualization."""
        return _build_network_arcs(self._airports, self._propagation_log)


# ── Helpers ──────────────────────────────────────────────────────


def _compute_disruption_level(delay_minutes: float) -> str:
    """Map current delay to a disruption level colour."""
    if delay_minutes >= 45:
        return "red"
    if delay_minutes >= 20:
        return "amber"
    return "green"


def _build_network_arcs(
    airports: dict[str, NetworkAirport],
    propagation_log: list[DelayPropagation],
) -> list[dict]:
    """Build arc metadata for map visualization."""
    # Build a set of airport pairs with propagation activity
    pair_delays: dict[tuple[str, str], float] = {}
    for p in propagation_log[-200:]:
        key = (p.source_icao, p.target_icao)
        pair_delays[key] = pair_delays.get(key, 0) + p.propagated_delay_minutes

    arcs = []
    home_icao = None
    for a in airports.values():
        if a.role == "home":
            home_icao = a.icao
            break

    if home_icao is None:
        return arcs

    home = airports[home_icao]
    for icao, airport in airports.items():
        if icao == home_icao:
            continue
        outbound_delay = pair_delays.get((home_icao, icao), 0)
        inbound_delay = pair_delays.get((icao, home_icao), 0)
        total_delay = outbound_delay + inbound_delay

        status = "green"
        if total_delay >= 60:
            status = "red"
        elif total_delay >= 20:
            status = "amber"
        elif airport.disruption_level != "green":
            status = airport.disruption_level

        arcs.append({
            "source": {
                "icao": home_icao,
                "iata": home.iata,
                "lat": home.lat,
                "lon": home.lon,
            },
            "target": {
                "icao": icao,
                "iata": airport.iata,
                "lat": airport.lat,
                "lon": airport.lon,
            },
            "status": status,
            "outbound_delay_minutes": round(outbound_delay, 1),
            "inbound_delay_minutes": round(inbound_delay, 1),
            "gdp_active": airport.gdp_active,
        })

    return arcs


# ── Singleton ────────────────────────────────────────────────────

_engine: NetworkEngine | None = None


def get_network_engine() -> NetworkEngine:
    """Get or create the singleton network engine."""
    global _engine
    if _engine is None:
        _engine = NetworkEngine()
    return _engine


def reset_network_engine() -> None:
    """Reset the singleton (useful for testing and sim reset)."""
    global _engine
    _engine = None
