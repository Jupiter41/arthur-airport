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
    "gdp_start",                 # one uniform hold per selected departure
    "gdp_end",                   # end marker; cannot release committed holds
    "open_security_lanes",       # additional lanes per terminal
    "gate_swap",                 # reassignment to an existing free gate
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

    Only disruptions reduce runway capacity. Lane windows add security capacity.
    GDP and gate reassignment are discrete shared-core commands at their start
    minute; they never create gates or reduce physical runway throughput.
    """
    from _common.effects import planning_window

    factor, lanes = planning_window([iv.to_dict() for iv in interventions],
                                    disruption.to_dict() if disruption else None, minute)
    return factor, lanes, 0
