"""REST contracts for durable decision history; replay input internals stay private."""

from typing import Any
from pydantic import BaseModel, Field
from models.domain import Bottleneck, Recommendation


class DecisionStage(BaseModel):
    stage: str
    at: str | None
    details: dict[str, Any] = Field(default_factory=dict)


class DecisionTimeline(BaseModel):
    id: str
    bottleneck_id: str | None
    bottleneck: Bottleneck | None
    recommendation: Recommendation | None
    alternatives: list[Recommendation]
    description: str
    status: str
    proposal_status: str | None
    proposal_id: str | None
    action_type: str | None
    parameters: dict[str, Any]
    stages: list[DecisionStage]
    predicted: dict[str, Any] | None
    outcome: dict[str, Any] | None
    receipt: dict[str, Any] | None
    dispatch_attempts: int
    failure_reason: str | None
    effect_model_version: str
    context_available: bool
    financial_signals: dict[str, Any]
    updated_at: str | None
    action_available: bool


class DecisionList(BaseModel):
    decisions: list[DecisionTimeline]
    total: int
    limit: int
    offset: int
