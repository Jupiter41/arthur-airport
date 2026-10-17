"""Decision audit trail — logs recommendations and measures outcomes.

P7.1–P7.3 of ROADMAP_PLANNING.md.

Maintains an in-memory audit log of all recommendations (operational
and planning), tracks application status, and computes prediction
accuracy metrics for the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from db.store import get_repository

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RecommendationLogEntry:
    """A single recommendation and its tracked outcome."""

    id: str = field(default_factory=lambda: str(uuid4()))
    type: str = "operational"  # operational | planning
    recommendation_text: str = ""
    action_type: str = ""
    predicted_saving_eur: float = 0.0
    confidence: float = 0.0
    was_applied: bool = False
    applied_at: str | None = None
    actual_saving_eur: float | None = None
    prediction_error_eur: float | None = None
    sim_day: int = 1
    sim_time: str = ""
    model_version: str = "v1.0"
    target_type: str = ""  # Flight | Terminal | Incident
    target_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "recommendation_text": self.recommendation_text,
            "action_type": self.action_type,
            "predicted_saving_eur": self.predicted_saving_eur,
            "confidence": self.confidence,
            "was_applied": self.was_applied,
            "applied_at": self.applied_at,
            "actual_saving_eur": self.actual_saving_eur,
            "prediction_error_eur": self.prediction_error_eur,
            "sim_day": self.sim_day,
            "sim_time": self.sim_time,
            "model_version": self.model_version,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "created_at": self.created_at,
        }


# ── Durable audit records ────────────────────────────────────



def _entries() -> list[RecommendationLogEntry]:
    entries = [RecommendationLogEntry(**d) for d in get_repository().list("RecommendationLog")]
    return sorted(entries, key=lambda e: (e.created_at, e.id))



def log_recommendation(
    recommendation_text: str,
    action_type: str,
    predicted_saving_eur: float,
    confidence: float,
    rec_type: str = "operational",
    sim_day: int = 1,
    sim_time: str = "",
    target_type: str = "",
    target_id: str = "",
) -> RecommendationLogEntry:
    """Log a new recommendation to the audit trail."""
    entry = RecommendationLogEntry(
        type=rec_type,
        recommendation_text=recommendation_text,
        action_type=action_type,
        predicted_saving_eur=predicted_saving_eur,
        confidence=confidence,
        sim_day=sim_day,
        sim_time=sim_time,
        target_type=target_type,
        target_id=target_id,
    )
    get_repository().put("RecommendationLog", entry.id, entry.to_dict())
    return entry


def mark_applied(rec_id: str, applied_at: str) -> bool:
    """Mark a recommendation as applied."""
    for entry in _entries():
        if entry.id == rec_id:
            entry.was_applied = True
            entry.applied_at = applied_at
            get_repository().put("RecommendationLog", entry.id, entry.to_dict())
            return True
    return False


def record_outcome(
    rec_id: str,
    actual_saving_eur: float,
) -> bool:
    """Record the measured outcome of an applied recommendation."""
    for entry in _entries():
        if entry.id == rec_id:
            entry.actual_saving_eur = actual_saving_eur
            if entry.predicted_saving_eur != 0:
                entry.prediction_error_eur = entry.predicted_saving_eur - actual_saving_eur
            else:
                entry.prediction_error_eur = -actual_saving_eur
            get_repository().put("RecommendationLog", entry.id, entry.to_dict())
            return True
    return False


def get_audit_log(
    rec_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Get paginated audit log entries."""
    filtered = _entries()
    if rec_type:
        filtered = [e for e in filtered if e.type == rec_type]

    total = len(filtered)
    # Most recent first
    entries = list(reversed(filtered))
    page = entries[offset:offset + limit]
    return [e.to_dict() for e in page], total


def get_audit_summary() -> dict:
    """Compute audit summary metrics for the dashboard panel."""
    entries = _entries()
    if not entries:
        return {
            "total_recommendations": 0,
            "applied_count": 0,
            "applied_pct": 0.0,
            "total_predicted_saving_eur": 0.0,
            "total_actual_saving_eur": 0.0,
            "prediction_accuracy_pct": 0.0,
            "avg_confidence": 0.0,
        }

    total = len(entries)
    applied = [e for e in entries if e.was_applied]
    measured = [e for e in applied if e.actual_saving_eur is not None]

    total_predicted = sum(e.predicted_saving_eur for e in applied)
    total_actual = sum(e.actual_saving_eur for e in measured) if measured else 0.0
    avg_confidence = sum(e.confidence for e in entries) / total if total else 0.0

    accuracy = 0.0
    measured_predicted = sum(e.predicted_saving_eur for e in measured)
    if measured_predicted > 0 and measured:
        accuracy = max(0.0, (1.0 - abs(measured_predicted - total_actual) / measured_predicted) * 100)

    return {
        "total_recommendations": total,
        "applied_count": len(applied),
        "applied_pct": round(len(applied) / total * 100, 1) if total else 0.0,
        "total_predicted_saving_eur": round(total_predicted, 2),
        "total_actual_saving_eur": round(total_actual, 2),
        "prediction_accuracy_pct": round(accuracy, 1),
        "avg_confidence": round(avg_confidence, 3),
        "measured_count": len(measured),
    }


def clear_audit_log() -> None:
    """Clear the audit log (for testing)."""
    for entry in _entries():
        get_repository().delete("RecommendationLog", entry.id)
