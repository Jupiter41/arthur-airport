"""Infrastructure configuration model for capacity planning scenarios.

Defines the configurable airport infrastructure parameters that differ between
planning scenarios (gates, runways, security lanes, baggage capacity, demand).

P2.2 of ROADMAP_PLANNING.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunwayConfig:
    """A single runway configuration."""

    id: str
    ils: bool = True
    length_m: int = 3500

    def to_dict(self) -> dict:
        return {"id": self.id, "ils": self.ils, "length_m": self.length_m}

    @classmethod
    def from_dict(cls, d: dict) -> RunwayConfig:
        return cls(id=d["id"], ils=d.get("ils", True), length_m=d.get("length_m", 3500))


@dataclass
class InfrastructureConfig:
    """Everything that can be changed in a capacity planning scenario.

    The ``baseline()`` classmethod returns the current KART configuration
    (the do-nothing scenario against which all changes are compared).
    """

    # Gates
    gates_per_terminal: dict[str, int] = field(
        default_factory=lambda: {"A": 14, "B": 14, "C": 14}
    )
    gate_wide_body_capable: dict[str, list[str]] = field(default_factory=dict)
    gate_international_capable: dict[str, list[str]] = field(default_factory=dict)

    # Runways
    runways: list[RunwayConfig] = field(default_factory=list)

    # Security
    security_lanes_per_terminal: dict[str, int] = field(
        default_factory=lambda: {"A": 4, "B": 3, "C": 4}
    )

    # Baggage
    screening_units: int = 6
    sorting_capacity_per_hour: int = 1800

    # Demand
    daily_flight_target: int = 420
    load_factor_mean: float = 0.80
    demand_growth_rate: float = 0.034  # annual CAGR for multi-year planning

    @classmethod
    def baseline(cls) -> InfrastructureConfig:
        """Current KART configuration — the do-nothing baseline."""
        return cls(
            gates_per_terminal={"A": 14, "B": 14, "C": 14},
            gate_wide_body_capable={
                "A": [f"A{i:02d}" for i in range(7, 10)],
                "B": [f"B{i:02d}" for i in range(7, 10)],
                "C": [f"C{i:02d}" for i in range(7, 10)],
            },
            gate_international_capable={
                "A": [f"A{i:02d}" for i in range(8, 15)],
                "B": [f"B{i:02d}" for i in range(8, 15)],
                "C": [f"C{i:02d}" for i in range(8, 15)],
            },
            runways=[
                RunwayConfig("09L", ils=True),
                RunwayConfig("09R", ils=False),
            ],
            security_lanes_per_terminal={"A": 4, "B": 3, "C": 4},
            screening_units=6,
            sorting_capacity_per_hour=1800,
            daily_flight_target=420,
            load_factor_mean=0.80,
            demand_growth_rate=0.034,
        )

    @property
    def total_gates(self) -> int:
        return sum(self.gates_per_terminal.values())

    @property
    def total_security_lanes(self) -> int:
        return sum(self.security_lanes_per_terminal.values())

    @property
    def runway_count(self) -> int:
        return len(self.runways)

    @property
    def ils_runway_count(self) -> int:
        return sum(1 for r in self.runways if r.ils)

    def to_dict(self) -> dict:
        return {
            "gates_per_terminal": self.gates_per_terminal,
            "gate_wide_body_capable": self.gate_wide_body_capable,
            "gate_international_capable": self.gate_international_capable,
            "runways": [r.to_dict() for r in self.runways],
            "security_lanes_per_terminal": self.security_lanes_per_terminal,
            "screening_units": self.screening_units,
            "sorting_capacity_per_hour": self.sorting_capacity_per_hour,
            "daily_flight_target": self.daily_flight_target,
            "load_factor_mean": self.load_factor_mean,
            "demand_growth_rate": self.demand_growth_rate,
        }

    @classmethod
    def from_dict(cls, d: dict) -> InfrastructureConfig:
        runways = [RunwayConfig.from_dict(r) for r in d.get("runways", [])]
        if not runways:
            runways = [RunwayConfig("09L", ils=True), RunwayConfig("09R", ils=False)]
        return cls(
            gates_per_terminal=d.get("gates_per_terminal", {"A": 14, "B": 14, "C": 14}),
            gate_wide_body_capable=d.get("gate_wide_body_capable", {}),
            gate_international_capable=d.get("gate_international_capable", {}),
            runways=runways,
            security_lanes_per_terminal=d.get("security_lanes_per_terminal", {"A": 4, "B": 3, "C": 4}),
            screening_units=d.get("screening_units", 6),
            sorting_capacity_per_hour=d.get("sorting_capacity_per_hour", 1800),
            daily_flight_target=d.get("daily_flight_target", 420),
            load_factor_mean=d.get("load_factor_mean", 0.80),
            demand_growth_rate=d.get("demand_growth_rate", 0.034),
        )


# ── Cost estimation constants (Eurocontrol Standard Inputs + ICAO) ──

COST_ESTIMATES: dict[str, dict[str, float]] = {
    "gate": {"capex": 8_000_000, "annual_opex": 120_000},
    "runway": {"capex": 800_000_000, "annual_opex": 12_000_000},
    "security_lane": {"capex": 250_000, "annual_opex": 204_400},  # 16h×€35/h×365d
    "screening_unit": {"capex": 2_000_000, "annual_opex": 300_000},
    "terminal": {"capex_per_gate": 12_000_000, "annual_opex_per_gate": 200_000},
}


def estimate_costs(baseline: InfrastructureConfig, scenario: InfrastructureConfig) -> dict:
    """Estimate CAPEX and annual OPEX delta from infrastructure differences.

    Returns a breakdown of costs by change type plus totals.
    """
    breakdown: list[dict] = []
    total_capex = 0.0
    total_opex = 0.0

    # Gate changes
    for t in sorted(set(baseline.gates_per_terminal) | set(scenario.gates_per_terminal)):
        delta = scenario.gates_per_terminal.get(t, 0) - baseline.gates_per_terminal.get(t, 0)
        if delta > 0:
            capex = delta * COST_ESTIMATES["gate"]["capex"]
            opex = delta * COST_ESTIMATES["gate"]["annual_opex"]
            breakdown.append({
                "item": f"+{delta} gate(s) in Terminal {t}",
                "capex_eur": capex, "annual_opex_eur": opex,
            })
            total_capex += capex
            total_opex += opex

    # Runway changes
    delta_runways = scenario.runway_count - baseline.runway_count
    if delta_runways > 0:
        capex = delta_runways * COST_ESTIMATES["runway"]["capex"]
        opex = delta_runways * COST_ESTIMATES["runway"]["annual_opex"]
        breakdown.append({
            "item": f"+{delta_runways} runway(s)",
            "capex_eur": capex, "annual_opex_eur": opex,
        })
        total_capex += capex
        total_opex += opex

    # Security lane changes
    for t in sorted(set(baseline.security_lanes_per_terminal) | set(scenario.security_lanes_per_terminal)):
        delta = scenario.security_lanes_per_terminal.get(t, 0) - baseline.security_lanes_per_terminal.get(t, 0)
        if delta > 0:
            capex = delta * COST_ESTIMATES["security_lane"]["capex"]
            opex = delta * COST_ESTIMATES["security_lane"]["annual_opex"]
            breakdown.append({
                "item": f"+{delta} security lane(s) in Terminal {t}",
                "capex_eur": capex, "annual_opex_eur": opex,
            })
            total_capex += capex
            total_opex += opex

    # Screening unit changes
    delta_screening = scenario.screening_units - baseline.screening_units
    if delta_screening > 0:
        capex = delta_screening * COST_ESTIMATES["screening_unit"]["capex"]
        opex = delta_screening * COST_ESTIMATES["screening_unit"]["annual_opex"]
        breakdown.append({
            "item": f"+{delta_screening} screening unit(s)",
            "capex_eur": capex, "annual_opex_eur": opex,
        })
        total_capex += capex
        total_opex += opex

    return {
        "breakdown": breakdown,
        "total_capex_eur": round(total_capex, 2),
        "total_annual_opex_eur": round(total_opex, 2),
    }
