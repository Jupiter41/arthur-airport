"""Pydantic domain models for flight-service."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FlightStatus(str, Enum):
    """All possible states in the flight lifecycle FSM."""
    SCHEDULED = "scheduled"
    BOARDING = "boarding"
    DELAYED = "delayed"
    DEPARTED = "departed"
    AIRBORNE = "airborne"
    APPROACH = "approach"
    LANDED = "landed"
    TAXIING = "taxiing"
    AT_GATE = "at_gate"
    ARRIVED = "arrived"
    CANCELLED = "cancelled"


class FlightDirection(str, Enum):
    """Whether a flight is arriving at or departing from KART."""
    ARRIVAL = "arrival"
    DEPARTURE = "departure"


class FlightType(str, Enum):
    """Operational category of a flight."""
    DOMESTIC = "domestic"
    INTERNATIONAL_SHORT = "international_short"
    INTERNATIONAL_LONG = "international_long"
    CARGO = "cargo"
    CHARTER = "charter"


class RouteCategory(str, Enum):
    """Distance-based route classification."""
    SHORT_HAUL = "short_haul"
    MEDIUM_HAUL = "medium_haul"
    LONG_HAUL = "long_haul"


class FlightSummary(BaseModel):
    """Lightweight flight representation returned by the list endpoint."""
    id: str
    flight_number: str
    airline_code: str
    direction: str
    status: str
    aircraft_type: str
    origin_iata: str
    destination_iata: str
    gate_id: Optional[str] = None
    runway_id: Optional[str] = None
    scheduled_time: str
    estimated_time: str
    delay_minutes: int = 0
    pax_count: int = 0
    seat_capacity: int = 0
    flight_type: Optional[str] = None
    route_category: Optional[str] = None
    flight_duration_minutes: Optional[int] = None
    arrival_estimated_time: Optional[str] = None

    model_config = {"from_attributes": True}


class FlightListResponse(BaseModel):
    """Paginated list of flight summaries."""
    total: int
    limit: int
    offset: int
    flights: list[FlightSummary]


class FlightDetail(BaseModel):
    """Full flight record with nested gate, runway, passenger, and baggage data."""
    id: str
    flight_number: str
    airline_code: str
    direction: str
    status: str
    aircraft_type: str
    aircraft_registration: str
    origin_iata: str
    destination_iata: str
    scheduled_time: str
    estimated_time: str
    actual_time: Optional[str] = None
    delay_minutes: int = 0
    delay_reason: Optional[str] = None
    gate: Optional[dict] = None
    runway: Optional[dict] = None
    passengers: Optional[dict] = None
    baggage: Optional[dict] = None
    history: list[dict] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class RunwayInfo(BaseModel):
    """Current state of a single runway."""
    id: str
    status: str
    current_use: str
    ils: bool
    arrivals_queued: int = 0
    departures_queued: int = 0


class GateInfo(BaseModel):
    """Current state of a single gate."""
    id: str
    terminal: str
    status: str
    flight_number: Optional[str] = None
    occupied_until: Optional[str] = None
    jetbridge: bool = False


class HoldRequest(BaseModel):
    """Request body to manually hold a flight (delay it)."""
    reason: str
    expected_duration_minutes: int


class CascadeResponse(BaseModel):
    """Response showing the cascade tree of delay effects for a flight."""
    flight_id: str
    flight_number: str
    delay_minutes: int
    cascade: dict
