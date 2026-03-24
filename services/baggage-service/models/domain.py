"""Pydantic domain models for baggage-service."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class BaggageStatus(str, Enum):
    DROPPED_OFF = "dropped_off"
    INDUCTED = "inducted"
    SCREENING = "screening"
    SORTING = "sorting"
    LOADED = "loaded"
    IN_HOLD = "in_hold"
    ARRIVED = "arrived"
    ON_CAROUSEL = "on_carousel"
    COLLECTED = "collected"
    LOST = "lost"
    FLAGGED = "flagged"
    OFFLOADED = "offloaded"
    HELD_FOR_REVIEW = "held_for_review"


class ZoneStatus(str, Enum):
    NORMAL = "normal"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class BaggageItem(BaseModel):
    id: str
    tag: str
    passenger_id: Optional[str] = None
    passenger_name: Optional[str] = None
    flight_number: Optional[str] = None
    flight_id: Optional[str] = None
    status: str
    weight_kg: Optional[float] = None
    is_dangerous_goods: bool = False
    dg_class: Optional[str] = None
    last_scan_zone: Optional[str] = None
    last_scan_at: Optional[str] = None

    model_config = {"from_attributes": True}


class BaggageDetail(BaseModel):
    id: str
    tag: str
    status: str
    weight_kg: Optional[float] = None
    is_dangerous_goods: bool = False
    dg_class: Optional[str] = None
    passenger: Optional[dict] = None
    flight: Optional[dict] = None
    scan_history: list[dict] = []


class ScanEvent(BaseModel):
    zone: str
    status: str
    at: str


class ZoneInfo(BaseModel):
    zone_id: str
    items: int
    status: str
    throughput_per_hour: int = 0
    utilisation_pct: int = 0


class FlowSummary(BaseModel):
    sim_time: Optional[str] = None
    total_in_system: int = 0
    by_status: dict[str, int] = {}
    flagged_active: int = 0
    system_failures_active: int = 0
    zones: list[ZoneInfo] = []


class FlowMap(BaseModel):
    zones: list[ZoneInfo] = []


class FlaggedItem(BaseModel):
    id: str
    tag: str
    passenger_name: Optional[str] = None
    flight_number: Optional[str] = None
    flag_reason: Optional[str] = None
    dg_class: Optional[str] = None
    current_zone: Optional[str] = None
    flagged_at: Optional[str] = None
    review_status: str = "pending"


class BaggageListResponse(BaseModel):
    total: int
    items: list[BaggageItem]


class FlaggedResponse(BaseModel):
    flagged: list[FlaggedItem]
