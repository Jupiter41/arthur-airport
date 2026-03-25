"""Pydantic domain models for passenger-service."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class PassengerStatus(str, Enum):
    CHECKED_IN = "checked_in"
    SECURITY_QUEUE = "security_queue"
    AIRSIDE = "airside"
    AT_GATE = "at_gate"
    BOARDED = "boarded"
    AIRBORNE = "airborne"
    DEPLANING = "deplaning"
    BAGGAGE_CLAIM = "baggage_claim"
    DEPARTED_AIRPORT = "departed_airport"
    MISSED_CONNECTION = "missed_connection"
    DISRUPTED = "disrupted"


class ConnectionRisk(str, Enum):
    OK = "ok"
    WATCH = "watch"
    AT_RISK = "at_risk"
    MISSED = "missed"


class PassengerSummary(BaseModel):
    id: str
    name: str
    pnr: str
    flight_number: Optional[str] = None
    status: str
    location_zone: Optional[str] = None
    seat: Optional[str] = None
    connection: bool = False
    special_assistance: bool = False

    model_config = {"from_attributes": True}


class PassengerDetail(BaseModel):
    id: str
    name: str
    pnr: str
    nationality: Optional[str] = None
    flight: Optional[dict] = None
    status: str
    location_zone: Optional[str] = None
    seat: Optional[str] = None
    connection: bool = False
    connection_flight_id: Optional[str] = None
    special_assistance: bool = False
    baggage: list[dict] = []
    alerts: list[dict] = []
    timeline: list[dict] = []

    model_config = {"from_attributes": True}


class SecurityInfo(BaseModel):
    queue_depth: int = 0
    wait_minutes: float = 0.0
    lanes_open: int = 4


class FlowSummary(BaseModel):
    sim_time: Optional[str] = None
    total_in_airport: int = 0
    by_status: dict[str, int] = {}
    security: dict[str, SecurityInfo] = {}
    connections_at_risk: int = 0
    connections_missed: int = 0


class ZoneHeatmap(BaseModel):
    zone_id: str
    density: int = 0
    capacity: int = 0
    load_pct: float = 0.0


class ForecastPoint(BaseModel):
    sim_time: str
    predicted_queue_depth: int = 0
    predicted_wait_minutes: float = 0.0


class CongestionRisk(BaseModel):
    detected: bool = False
    estimated_onset_sim_time: Optional[str] = None
    confidence: float = 0.0


class ForecastResponse(BaseModel):
    terminal: str
    sim_time: Optional[str] = None
    window_minutes: int = 90
    model_trained: bool = False
    forecast: list[ForecastPoint] = []
    congestion_risk: Optional[CongestionRisk] = None
    feature_importance: Optional[dict[str, float]] = None


class AtRiskConnection(BaseModel):
    passenger_id: str
    name: str
    pnr: str
    inbound_flight: Optional[str] = None
    inbound_delay_minutes: int = 0
    connection_flight: Optional[str] = None
    connection_departs_in_minutes: int = 0
    mct_minutes: int = 45
    risk_level: str = "ok"
    baggage_count: int = 0


class PassengerAlert(BaseModel):
    type: str
    message: str
    issued_at: str
    passenger_id: Optional[str] = None
    flight_id: Optional[str] = None
    urgency: str = "info"
