"""Pre-built scenario templates for common capacity planning questions.

Phase 5 of ROADMAP_PLANNING.md (P5.1–P5.4).
Each function returns a ready-to-run ``PlanningScenario`` with sensible
cost defaults derived from industry benchmarks.
"""

from __future__ import annotations

from dataclasses import replace

from engine.infrastructure import InfrastructureConfig, RunwayConfig
from scenarios.model import PlanningScenario


# ── P5.1 — Gate addition ────────────────────────────────────

def create_gate_scenario(terminal: str, additional_gates: int) -> PlanningScenario:
    """Add *additional_gates* gates to *terminal*.

    Cost basis: €8 M capex per gate (industry average for contact gates),
    €120 K/year maintenance per gate.
    """
    baseline = InfrastructureConfig.baseline()
    current = baseline.gates_per_terminal.get(terminal, 0)
    new_config = replace(
        baseline,
        gates_per_terminal={
            **baseline.gates_per_terminal,
            terminal: current + additional_gates,
        },
    )
    return PlanningScenario(
        name=f"Add {additional_gates} gate(s) to Terminal {terminal}",
        description=(
            f"Expand Terminal {terminal} from {current} to "
            f"{current + additional_gates} gates."
        ),
        infrastructure=new_config,
        capex_eur=additional_gates * 8_000_000,
        opex_delta_eur=additional_gates * 120_000,
        monte_carlo_runs=200,
        horizon="month",
        years_horizon=25,
        discount_rate=0.07,
    )


# ── P5.2 — Runway addition ─────────────────────────────────

def create_runway_scenario(
    runway_id: str,
    ils_capable: bool,
    length_m: int = 3000,
) -> PlanningScenario:
    """Add a new runway to KART.

    Cost basis: scaled from Heathrow T5 runway estimate — ~€800 M for
    a regional-hub-sized runway. Annual opex ~€12 M (maintenance, ATC,
    lighting, de-icing).
    """
    baseline = InfrastructureConfig.baseline()
    new_runways = baseline.runways + [
        RunwayConfig(runway_id, ils=ils_capable, length_m=length_m),
    ]
    new_config = replace(baseline, runways=new_runways)
    return PlanningScenario(
        name=f"Add runway {runway_id}",
        description=(
            f"Add {'ILS-capable' if ils_capable else 'visual-only'} "
            f"runway {runway_id} ({length_m} m)."
        ),
        infrastructure=new_config,
        capex_eur=800_000_000,
        opex_delta_eur=12_000_000,
        monte_carlo_runs=100,
        horizon="year",
        years_horizon=30,
        discount_rate=0.06,
    )


# ── P5.3 — New route ───────────────────────────────────────

def create_route_scenario(
    destination_iata: str,
    daily_flights: int,
    aircraft_type: str = "A320",
) -> PlanningScenario:
    """Add a new route from KART to *destination_iata*.

    Revenue is estimated from the BTS demand model for the city pair.
    No infrastructure capex — this is a pure demand-side scenario.
    """
    baseline = InfrastructureConfig.baseline()
    return PlanningScenario(
        name=f"New route ART → {destination_iata} ({daily_flights} daily)",
        description=(
            f"Launch {daily_flights} daily {aircraft_type} rotation(s) "
            f"to {destination_iata}."
        ),
        infrastructure=baseline,
        new_routes=[
            {
                "origin": "ART",
                "destination": destination_iata,
                "daily_flights": daily_flights,
                "aircraft_type": aircraft_type,
            },
        ],
        demand_source="bts",
        capex_eur=0,
        opex_delta_eur=0,
        monte_carlo_runs=100,
        horizon="month",
        years_horizon=5,
        discount_rate=0.08,
    )


# ── P5.4 — Security lane optimisation ──────────────────────

def create_security_scenario(lanes_delta: dict[str, int]) -> PlanningScenario:
    """Adjust security lane counts per terminal.

    *lanes_delta* maps terminal letters to the number of lanes to add
    (or remove if negative), e.g. ``{"A": 1, "B": 1}``.

    Cost basis: staffing only — 16 h/day, €35/h, 365 days/year per lane.
    """
    baseline = InfrastructureConfig.baseline()
    new_lanes = {
        terminal: baseline.security_lanes_per_terminal.get(terminal, 0) + lanes_delta.get(terminal, 0)
        for terminal in {*baseline.security_lanes_per_terminal, *lanes_delta}
    }
    annual_staffing_cost = sum(
        delta * 365 * 16 * 35
        for delta in lanes_delta.values()
        if delta > 0
    )
    new_config = replace(baseline, security_lanes_per_terminal=new_lanes)
    return PlanningScenario(
        name=f"Security lanes: {lanes_delta}",
        description=(
            "Adjust security lanes: "
            + ", ".join(f"Terminal {t}: {'+' if d > 0 else ''}{d}" for t, d in lanes_delta.items())
            + "."
        ),
        infrastructure=new_config,
        capex_eur=0,
        opex_delta_eur=annual_staffing_cost,
        monte_carlo_runs=200,
        horizon="week",
        years_horizon=3,
        discount_rate=0.08,
    )


# ── Template catalogue ──────────────────────────────────────

TEMPLATE_CATALOGUE = {
    "add_gate": {
        "name": "Add Gate(s)",
        "description": "Add contact gates to a terminal",
        "params": {"terminal": "str (A/B/C)", "additional_gates": "int"},
        "factory": create_gate_scenario,
    },
    "add_runway": {
        "name": "Add Runway",
        "description": "Add a new runway to the airport",
        "params": {"runway_id": "str", "ils_capable": "bool", "length_m": "int (optional, default 3000)"},
        "factory": create_runway_scenario,
    },
    "new_route": {
        "name": "New Route",
        "description": "Launch a new route from ART",
        "params": {"destination_iata": "str", "daily_flights": "int", "aircraft_type": "str (optional)"},
        "factory": create_route_scenario,
    },
    "security_lanes": {
        "name": "Security Lane Adjustment",
        "description": "Add or remove security screening lanes",
        "params": {"lanes_delta": "dict[str, int] — terminal → lane count change"},
        "factory": create_security_scenario,
    },
}
