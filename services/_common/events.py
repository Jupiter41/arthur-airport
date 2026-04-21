"""Shared Pydantic event schemas — single source of truth for Kafka envelopes.

Usage (producer):
    from _common.events import EventEnvelope, FlightStatusChangedPayload
    envelope = EventEnvelope.build("FlightStatusChanged", sim_time, "flight-service",
                                   FlightStatusChangedPayload(...).model_dump())

Usage (consumer validation):
    from _common.events import EventEnvelope
    envelope = EventEnvelope.model_validate(raw_dict)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Envelope ─────────────────────────────────────────────────


class EventEnvelope(BaseModel):
    """Standard Kafka event envelope (EVENT_BUS.md §4)."""

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    schema_version: str = "1.0"
    produced_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sim_time: datetime
    producer: str
    payload: dict

    @classmethod
    def build(
        cls,
        event_type: str,
        sim_time: datetime,
        producer: str,
        payload: dict,
    ) -> "EventEnvelope":
        return cls(
            event_type=event_type,
            sim_time=sim_time,
            producer=producer,
            payload=payload,
        )

    def to_json_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")


# ── sim.clock ────────────────────────────────────────────────


class SimClockTickPayload(BaseModel):
    sim_time: datetime
    real_time: datetime
    speed_multiplier: int | float
    tick_number: int
    day_of_sim: int
    step_minutes: int = 1
    mode: str = "REALTIME"


# ── flights.events ───────────────────────────────────────────


class FlightStatusChangedPayload(BaseModel):
    flight_id: str
    flight_number: str
    previous_status: str
    new_status: str
    delay_minutes: int = 0
    delay_reason: Optional[str] = None
    gate_id: Optional[str] = None
    estimated_time: Optional[datetime] = None
    affected_pax_count: int = 0


class FlightGateAssignedPayload(BaseModel):
    flight_id: str
    flight_number: str
    previous_gate_id: Optional[str] = None
    new_gate_id: str
    reason: Optional[str] = None
    effective_at: Optional[datetime] = None


class FlightRunwayAssignedPayload(BaseModel):
    flight_id: str
    flight_number: str
    runway_id: str
    operation: str
    scheduled_at: Optional[datetime] = None


class FlightCancelledPayload(BaseModel):
    flight_id: str
    flight_number: str
    reason: str
    affected_pax_count: int = 0
    rebooking_required: bool = True


# ── passengers.events ────────────────────────────────────────


class PassengerStatusChangedPayload(BaseModel):
    passenger_id: str
    pnr: str
    flight_id: str
    previous_status: str
    new_status: str
    location_zone: Optional[str] = None
    at: Optional[datetime] = None


class PassengerAlertPayload(BaseModel):
    passenger_id: str
    pnr: str
    alert_type: str
    message: str
    urgency: str = "medium"
    at: Optional[datetime] = None


class SecurityCongestionDetectedPayload(BaseModel):
    terminal: str
    queue_depth: int
    wait_minutes: float
    consecutive_ticks_over_threshold: int = 0
    effective_throughput_pax_per_hr: float = 0
    slowdown_factor: float = 1.0
    forecast_queue_depth: int = 0
    at: Optional[datetime] = None


# ── baggage.events ───────────────────────────────────────────


class BaggageStatusChangedPayload(BaseModel):
    baggage_id: str
    tag: str
    passenger_id: str
    flight_id: str
    previous_status: str
    new_status: str
    scan_zone: Optional[str] = None
    at: Optional[datetime] = None


class BaggageFlaggedPayload(BaseModel):
    baggage_id: str
    tag: str
    passenger_id: str
    flight_id: str
    flag_reason: str
    dg_class: Optional[str] = None
    scan_zone: Optional[str] = None
    at: Optional[datetime] = None


# ── weather.events ───────────────────────────────────────────


class WeatherStateChangedPayload(BaseModel):
    weather_id: str
    previous_category: str
    new_category: str
    visibility_m: float
    wind_direction: int = 0
    wind_speed_kt: float = 0
    wind_gust_kt: float = 0
    ceiling_ft: float = 0
    temperature_c: float = 0
    phenomena: list[str] = Field(default_factory=list)
    runway_impact: Optional[str] = None
    recommended_arrival_rate: Optional[int] = None
    recommended_departure_rate: Optional[int] = None
    at: Optional[datetime] = None


class METARIssuedPayload(BaseModel):
    raw: str
    at: Optional[datetime] = None


# ── incidents.events ─────────────────────────────────────────


class IncidentCreatedPayload(BaseModel):
    incident_id: str
    type: str
    severity: str
    trigger: str = "probabilistic"
    title: str = ""
    description: str = ""
    location: Optional[str] = None
    affected_entity_ids: list[str] = Field(default_factory=list)
    protocol: Optional[str] = None
    started_at: Optional[datetime] = None


class IncidentStatusChangedPayload(BaseModel):
    incident_id: str
    previous_status: str
    new_status: str
    update_note: Optional[str] = None
    at: Optional[datetime] = None


class IncidentCascadedPayload(BaseModel):
    parent_incident_id: str
    child_incident_id: str
    cascade_type: str
    description: str = ""
    affected_entity_ids: list[str] = Field(default_factory=list)
    at: Optional[datetime] = None


# ── incidents.alerts ─────────────────────────────────────────


class IncidentAlertPayload(BaseModel):
    incident_id: str
    severity: str
    title: str
    short_message: str = ""
    affected_zones: list[str] = Field(default_factory=list)
    dashboard_color: str = "yellow"
    sound_alert: bool = False
    at: Optional[datetime] = None


# ── incidents.inject ─────────────────────────────────────────


class InjectIncidentPayload(BaseModel):
    type: str
    severity: str
    location: Optional[str] = None
    trigger: str = "manual"
    requested_by: str = "operator-dashboard"
    at: Optional[datetime] = None


# ── Bulk mode ────────────────────────────────────────────────


class BulkStateSnapshotPayload(BaseModel):
    service: str
    summary: dict


# ── Lookup ───────────────────────────────────────────────────

PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "SimClockTick": SimClockTickPayload,
    "FlightStatusChanged": FlightStatusChangedPayload,
    "FlightGateAssigned": FlightGateAssignedPayload,
    "FlightRunwayAssigned": FlightRunwayAssignedPayload,
    "FlightCancelled": FlightCancelledPayload,
    "PassengerStatusChanged": PassengerStatusChangedPayload,
    "PassengerAlert": PassengerAlertPayload,
    "SecurityCongestionDetected": SecurityCongestionDetectedPayload,
    "BaggageStatusChanged": BaggageStatusChangedPayload,
    "BaggageFlagged": BaggageFlaggedPayload,
    "WeatherStateChanged": WeatherStateChangedPayload,
    "METARIssued": METARIssuedPayload,
    "IncidentCreated": IncidentCreatedPayload,
    "IncidentStatusChanged": IncidentStatusChangedPayload,
    "IncidentCascaded": IncidentCascadedPayload,
    "IncidentAlert": IncidentAlertPayload,
    "InjectIncident": InjectIncidentPayload,
    "BulkStateSnapshot": BulkStateSnapshotPayload,
}
