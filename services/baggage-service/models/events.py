"""Kafka event Pydantic models for baggage-service."""

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    schema_version: str = "1.0"
    produced_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sim_time: datetime
    producer: str
    payload: dict


def make_event(event_type: str, sim_time: datetime, producer: str, payload: dict) -> str:
    envelope = EventEnvelope(
        event_type=event_type,
        sim_time=sim_time,
        producer=producer,
        payload=payload,
    )
    return envelope.model_dump_json()
