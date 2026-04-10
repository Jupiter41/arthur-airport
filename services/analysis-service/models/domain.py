"""Domain models for the analysis-service.

Defines Bottleneck, Recommendation, WhatIfRequest/Response, and AnalysisLog.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Bottleneck ───────────────────────────────────────────────


class BottleneckSeverity(str, Enum):
    WARNING = "warning"
    CRITICAL = "critical"


class BottleneckType(str, Enum):
    SECURITY_QUEUE = "security_queue"
    GATE_UTILISATION = "gate_utilisation"
    BAGGAGE_THROUGHPUT = "baggage_throughput"
    CONNECTION_CLUSTER = "connection_cluster"
    GROUND_VEHICLE = "ground_vehicle"
    RUNWAY_CAPACITY = "runway_capacity"


class Bottleneck(BaseModel):
    """A detected operational bottleneck requiring attention."""
    id: str = Field(..., description="Unique bottleneck ID")
    type: BottleneckType
    severity: BottleneckSeverity
    zone: str = Field(..., description="Affected zone or service area")
    root_cause: str = Field(..., description="Human-readable root cause description")
    estimated_duration_minutes: float = Field(
        ..., description="Estimated duration before natural resolution"
    )
    affected_entity_count: int = Field(
        ..., description="Number of affected entities (flights, passengers, bags)"
    )
    detected_at: datetime = Field(..., description="Sim time of detection")
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific metrics (queue depth, utilisation %, etc.)",
    )
    resolved_at: datetime | None = None


# ── Recommendation ───────────────────────────────────────────


class ActionType(str, Enum):
    OPEN_SECURITY_LANE = "open_security_lane"
    EARLY_GATE_CALL = "early_gate_call"
    REDIRECT_CHECKIN = "redirect_checkin"
    REASSIGN_GATE = "reassign_gate"
    DELAY_TAXI = "delay_taxi"
    SWAP_GATES = "swap_gates"
    HOLD_CONNECTING_FLIGHT = "hold_connecting_flight"
    FAST_TRACK_PASSENGERS = "fast_track_passengers"
    REBOOK_PASSENGERS = "rebook_passengers"
    GROUND_DELAY_PROGRAM = "ground_delay_program"
    REDISTRIBUTE_VEHICLES = "redistribute_vehicles"
    DEFER_TASK = "defer_task"
    REDIRECT_BAGGAGE = "redirect_baggage"
    EXPEDITE_LOADING = "expedite_loading"


class Recommendation(BaseModel):
    """A ranked intervention recommendation for a detected bottleneck."""
    id: str = Field(..., description="Unique recommendation ID")
    bottleneck_id: str = Field(..., description="Related bottleneck ID")
    action_type: ActionType
    description: str = Field(..., description="Human-readable action description")
    expected_impact: str = Field(
        ..., description="Quantified expected improvement"
    )
    cost: str = Field(
        ..., description="Estimated cost (staff hours, delay minutes, etc.)"
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in projected outcome"
    )
    expiry_sim_time: datetime = Field(
        ..., description="After this sim_time the recommendation is stale"
    )
    priority_rank: int = Field(
        ..., ge=1, description="Rank among all active recommendations"
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific parameters (flight_id, lane, terminal, etc.)",
    )
    applied: bool = False
    applied_at: datetime | None = None


# ── What-If ──────────────────────────────────────────────────


class WhatIfAction(BaseModel):
    """A proposed action for what-if analysis."""
    action_type: ActionType
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class WhatIfRequest(BaseModel):
    """Request for what-if projection."""
    actions: list[WhatIfAction] = Field(
        ..., min_length=1, max_length=3,
        description="1-3 proposed actions to evaluate",
    )
    horizon_minutes: int = Field(
        default=60, ge=5, le=120,
        description="Simulation horizon in sim-minutes",
    )


class KPIProjection(BaseModel):
    """Projected KPIs after applying an action."""
    action_index: int
    delay_minutes_total: float
    missed_connections: int
    avg_queue_depth: float
    cascade_depth: int
    gate_utilisation_pct: float
    baggage_throughput_pct: float
    confidence: float = Field(..., ge=0.0, le=1.0)


class WhatIfResponse(BaseModel):
    """Response from what-if projection."""
    baseline: KPIProjection
    projections: list[KPIProjection]
    sim_time_at_request: datetime
    horizon_minutes: int


# ── Analysis Log ─────────────────────────────────────────────


class AnalysisLogEntry(BaseModel):
    """Record of a what-if query or recommendation application."""
    id: str
    timestamp: datetime
    entry_type: str  # "what_if" | "recommendation_applied" | "autonomous_action"
    action: WhatIfAction | None = None
    projected_outcome: KPIProjection | None = None
    actual_outcome: KPIProjection | None = None
    operator_applied: bool = False


# ── Autonomous Mode ──────────────────────────────────────────


class AutonomousMode(str, Enum):
    """P5-1-5: Autonomous mode options."""
    OFF = "off"
    RULE_BASED = "rule_based"
    THRESHOLD = "threshold"
    RL_AGENT = "rl_agent"


class AutonomousSettings(BaseModel):
    """Configuration for autonomous operations mode."""
    enabled: bool = False
    mode: AutonomousMode = Field(
        default=AutonomousMode.THRESHOLD,
        description="Autonomous decision mode: off, rule_based, threshold, rl_agent",
    )
    confidence_threshold: float = Field(
        default=0.80, ge=0.5, le=1.0,
        description="Minimum confidence score to auto-apply",
    )
    check_interval_sim_minutes: int = Field(
        default=5, ge=1, le=30,
        description="How often to evaluate recommendations",
    )
    blocked_actions: list[ActionType] = Field(
        default_factory=lambda: [
            ActionType.GROUND_DELAY_PROGRAM,
        ],
        description="Actions that always require human confirmation",
    )
