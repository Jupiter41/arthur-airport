"""Pydantic models for scenario definitions and run results."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ScenarioEventType(str, Enum):
    """Incident types that can be injected by a scenario."""
    RUNWAY_INCURSION = "runway_incursion"
    BAGGAGE_FIRE = "baggage_fire"
    SECURITY_BREACH = "security_breach"
    SYSTEM_FAILURE = "system_failure"
    SEVERE_WEATHER = "severe_weather"


class ScenarioSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WeatherLock(str, Enum):
    """Weather states that can be locked for scenario seeding."""
    CAVOK = "CAVOK"
    VMC = "VMC"
    IMC = "IMC"
    LIFR = "LIFR"


class SeedOverrides(BaseModel):
    """Optional overrides for the simulation seed when running a scenario."""
    weather: Optional[WeatherLock] = None
    daily_flights: Optional[int] = Field(None, ge=10, le=1000)
    load_factor: Optional[float] = Field(None, ge=0.1, le=1.0)


class ScenarioEvent(BaseModel):
    """A single event to inject at a given sim-time offset."""
    at_sim_offset_minutes: int = Field(..., ge=0, description="Minutes after scenario start")
    type: ScenarioEventType
    severity: ScenarioSeverity
    location: str
    trigger: str = "manual"
    description: Optional[str] = None


class OutcomeCondition(str, Enum):
    """Comparison operators for expected outcome assertions."""
    GTE = ">="
    LTE = "<="
    GT = ">"
    LT = "<"
    EQ = "=="


class ExpectedOutcome(BaseModel):
    """An assertion on a metric value that should hold within a time window."""
    metric: str
    condition: str  # e.g. ">= 10"
    within_sim_minutes: int = Field(..., ge=1)


class ScenarioDefinition(BaseModel):
    """Full scenario definition as parsed from a YAML file."""
    name: str
    description: str
    sim_speed: int = 60
    start_time: str = "2024-06-15T06:00:00"
    duration_sim_minutes: int = Field(..., ge=1)
    seed_overrides: Optional[SeedOverrides] = None
    events: list[ScenarioEvent] = Field(default_factory=list)
    expected_outcomes: list[ExpectedOutcome] = Field(default_factory=list)


class MetricSnapshot(BaseModel):
    """A point-in-time capture of simulation metrics."""
    sim_time: str
    offset_minutes: int
    flights_delayed_current: int = 0
    holding_stack_depth: int = 0
    cascade_depth_max: int = 0
    avg_delay_minutes: float = 0.0
    missed_connections: int = 0
    security_queue_max: int = 0
    incident_count_active: int = 0
    flights_cancelled: int = 0
    total_delay_minutes: int = 0
    pax_disrupted: int = 0


class OutcomeResult(BaseModel):
    """Result of evaluating a single expected outcome."""
    metric: str
    condition: str
    expected: str
    actual: float
    passed: bool
    evaluated_at_offset_minutes: int


class ScenarioRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ScenarioRunResult(BaseModel):
    """Full result of a scenario run."""
    run_id: str
    scenario_name: str
    status: ScenarioRunStatus
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    sim_start_time: str = ""
    sim_end_time: str = ""
    duration_sim_minutes: int = 0
    events_injected: int = 0
    metric_snapshots: list[MetricSnapshot] = Field(default_factory=list)
    outcome_results: list[OutcomeResult] = Field(default_factory=list)
    passed: bool = False
    summary: str = ""
