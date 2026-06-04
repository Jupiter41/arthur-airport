"""Counterfactual delay analysis (1B — ROADMAP_USECASE.md).

Provides:
- ``Intervention`` dataclass: a planned operator decision (GDP, lane open, …) at a sim minute.
- ``Disruption``: a synthetic baseline disruption applied identically to baseline and
  counterfactual replays so that delta KPIs isolate intervention timing rather than randomness.
- helpers used by the engine to apply interventions during a tick.

The engine is intentionally simple: interventions multiplicatively adjust runway/security
capacity and gate counts within a window. This keeps replays deterministic and fast.
"""

from __future__ import annotations

from dataclasses import dataclass, field


VALID_ACTIONS = {
    "gdp_start",                 # apply runway capacity cap until duration ends or gdp_end
    "gdp_end",                   # explicit early end of an active GDP
    "open_security_lanes",       # additional lanes per terminal
    "gate_swap",                 # additional gates available globally
}


@dataclass
class Intervention:
    """A planned decision applied during the simulated day.

    Attributes:
        action: one of VALID_ACTIONS
        sim_minute: absolute minute-of-day (0..1439) when the action takes effect
        duration_minutes: how long the action remains active
        params: action-specific parameters
    """

    action: str
    sim_minute: int
    duration_minutes: int = 60
    params: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"Unknown intervention action: {self.action!r}")
        self.sim_minute = max(0, min(1439, int(self.sim_minute)))
        self.duration_minutes = max(1, int(self.duration_minutes))

    def is_active(self, minute: int, gdp_end_minute: int | None = None) -> bool:
        end_minute = self.sim_minute + self.duration_minutes
        if self.action == "gdp_start" and gdp_end_minute is not None:
            end_minute = min(end_minute, gdp_end_minute)
        return self.sim_minute <= minute < end_minute

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "sim_minute": self.sim_minute,
            "duration_minutes": self.duration_minutes,
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Intervention":
        return cls(
            action=raw["action"],
            sim_minute=int(raw.get("sim_minute", raw.get("sim_minutes", 0))),
            duration_minutes=int(raw.get("duration_minutes", 60)),
            params=dict(raw.get("params", {})),
        )


@dataclass
class Disruption:
    """A synthetic baseline disruption (e.g. runway closed, weather event).

    Applied identically to baseline and counterfactual replays so KPI deltas
    cleanly attribute to intervention choices.
    """

    sim_minute: int = 60
    duration_minutes: int = 120
    capacity_pct: float = 0.5  # cap on runway capacity during the window

    def is_active(self, minute: int) -> bool:
        return self.sim_minute <= minute < self.sim_minute + self.duration_minutes

    def to_dict(self) -> dict:
        return {
            "sim_minute": self.sim_minute,
            "duration_minutes": self.duration_minutes,
            "capacity_pct": self.capacity_pct,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Disruption":
        return cls(
            sim_minute=int(raw.get("sim_minute", 60)),
            duration_minutes=int(raw.get("duration_minutes", 120)),
            capacity_pct=float(raw.get("capacity_pct", 0.5)),
        )


def aggregate_capacity_factor(
    interventions: list[Intervention],
    disruption: Disruption | None,
    minute: int,
) -> tuple[float, int, int]:
    """Compute (runway_capacity_factor, extra_security_lanes, extra_gates) at minute.

    - Disruption capacity caps at ``disruption.capacity_pct``.
    - ``gdp_start`` interventions multiply runway capacity by ``params.cap_pct`` (default 0.7),
      taking the *minimum* of all active GDPs.
    - ``open_security_lanes`` add ``params.lanes`` (default 1) — summed across active interventions.
    - ``gate_swap`` adds ``params.delta`` gates (default 1) — summed across active interventions.
    - A ``gdp_end`` action terminates GDPs that started before its sim_minute.
    """
    cap_factor = 1.0
    extra_lanes = 0
    extra_gates = 0

    # Find any gdp_end before this minute
    gdp_end_minute = None
    for iv in interventions:
        if iv.action == "gdp_end" and iv.sim_minute <= minute:
            if gdp_end_minute is None or iv.sim_minute < gdp_end_minute:
                gdp_end_minute = iv.sim_minute

    if disruption and disruption.is_active(minute):
        cap_factor = min(cap_factor, max(0.0, disruption.capacity_pct))

    for iv in interventions:
        if not iv.is_active(minute, gdp_end_minute):
            continue
        if iv.action == "gdp_start":
            cap_pct = float(iv.params.get("cap_pct", 0.7))
            cap_factor = min(cap_factor, max(0.0, cap_pct))
        elif iv.action == "open_security_lanes":
            extra_lanes += int(iv.params.get("lanes", 1))
        elif iv.action == "gate_swap":
            extra_gates += int(iv.params.get("delta", 1))

    return cap_factor, extra_lanes, extra_gates
