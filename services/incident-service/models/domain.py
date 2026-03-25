"""Pydantic domain models for incident-service."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IncidentStatus(str, Enum):
    ACTIVE = "active"
    CONTAINED = "contained"
    RESOLVED = "resolved"


class IncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentType(str, Enum):
    RUNWAY_INCURSION = "runway_incursion"
    BAGGAGE_FIRE = "baggage_fire"
    SECURITY_BREACH = "security_breach"
    SEVERE_WEATHER = "severe_weather"
    SYSTEM_FAILURE = "system_failure"


class InjectRequest(BaseModel):
    type: str
    severity: str
    location: str
    description: str = ""
    subtype: str = ""


class ContainRequest(BaseModel):
    note: str = ""


class ResolveRequest(BaseModel):
    note: str = ""


class CascadeTreeNode(BaseModel):
    id: str
    type: str
    severity: str = ""
    status: str = ""
    description: str = ""
    affected_count: int = 0
    children: list["CascadeTreeNode"] = Field(default_factory=list)


class TimelineEntry(BaseModel):
    status: str
    note: str
    at: str


class IncidentSummary(BaseModel):
    id: str
    type: str
    severity: str
    status: str
    trigger: str = ""
    title: str = ""
    location: str = ""
    started_at: str = ""
    resolved_at: Optional[str] = None
    protocol: str = ""
    cascade_depth: int = 0

    model_config = {"from_attributes": True}


class IncidentDetail(BaseModel):
    id: str
    type: str
    severity: str
    status: str
    trigger: str = ""
    title: str = ""
    description: str = ""
    location: str = ""
    protocol: str = ""
    started_at: str = ""
    resolved_at: Optional[str] = None
    contained_at: Optional[str] = None
    estimated_resolution_at: Optional[str] = None
    ttr_remaining: Optional[int] = None
    cascade_tree: Optional[CascadeTreeNode] = None
    affected_flights: list[dict] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class IncidentListResponse(BaseModel):
    total: int
    incidents: list[IncidentSummary]


class AlertItem(BaseModel):
    incident_id: str
    severity: str
    title: str
    short_message: str
    affected_zones: list[str] = Field(default_factory=list)
    dashboard_color: str = "yellow"
    sound_alert: bool = False
    age_minutes: int = 0
    at: str = ""


class AlertsResponse(BaseModel):
    alerts: list[AlertItem]


class IncidentReport(BaseModel):
    incident_id: str
    report_generated_at: str
    title: str
    type: str
    severity: str
    trigger: str = ""
    timeline_summary: str = ""
    total_flights_affected: int = 0
    total_delay_minutes_caused: int = 0
    cascade_events: int = 0
    protocols_activated: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ProtocolStatusResponse(BaseModel):
    """Active emergency protocol status."""

    effective_protocol: str | None = None
    effective_description: str = ""
    active_protocols: dict[str, list[str]] = Field(default_factory=dict)
    evacuation_active: bool = False
