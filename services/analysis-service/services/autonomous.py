"""Autonomous operations mode.

When enabled, automatically applies the top recommendation every N sim-minutes
if its confidence score exceeds the configured threshold.

Safety guards prevent autonomous application of destructive actions
(flight cancellation, runway closure, terminal evacuation).

P2-4-1 through P2-4-4.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import uuid4

from models.domain import (
    ActionType,
    AnalysisLogEntry,
    AutonomousSettings,
    Recommendation,
)
from services.whatif import _log_entry

logger = logging.getLogger(__name__)

# ── Autonomous settings (mutable at runtime) ────────────────

_settings = AutonomousSettings()

# P2-4-4: Safety guards — these actions ALWAYS require human confirmation
SAFETY_GUARDED_ACTIONS: set[ActionType] = {
    ActionType.GROUND_DELAY_PROGRAM,
    ActionType.REBOOK_PASSENGERS,
}

# Autonomous action log
_action_log: list[dict] = []
MAX_ACTION_LOG = 200

# Last check time to enforce interval
_last_check_sim_time: datetime | None = None


def get_settings() -> AutonomousSettings:
    return _settings


def update_settings(new: AutonomousSettings) -> AutonomousSettings:
    global _settings
    _settings = new
    logger.info(
        "Autonomous mode %s (threshold=%.2f, interval=%d min)",
        "enabled" if _settings.enabled else "disabled",
        _settings.confidence_threshold,
        _settings.check_interval_sim_minutes,
    )
    return _settings


def get_action_log() -> list[dict]:
    return list(_action_log)


def should_evaluate(sim_time: datetime | None) -> bool:
    """Check if it's time to evaluate autonomous recommendations."""
    global _last_check_sim_time
    if not _settings.enabled or sim_time is None:
        return False

    if _last_check_sim_time is None:
        _last_check_sim_time = sim_time
        return True

    interval = timedelta(minutes=_settings.check_interval_sim_minutes)
    if sim_time - _last_check_sim_time >= interval:
        _last_check_sim_time = sim_time
        return True

    return False


def evaluate_and_apply(
    recommendations: list[Recommendation],
    sim_time: datetime,
) -> list[dict]:
    """P2-4-1 + P2-4-2: Evaluate and potentially auto-apply top recommendations.

    Returns a list of actions taken (empty if none met threshold).
    """
    if not _settings.enabled:
        return []

    actions_taken = []

    for rec in recommendations:
        if rec.applied:
            continue

        # P2-4-4: Safety guard check
        if rec.action_type in SAFETY_GUARDED_ACTIONS:
            logger.info(
                "Autonomous: skipping safety-guarded action %s (%s)",
                rec.action_type, rec.id,
            )
            continue

        if rec.action_type in _settings.blocked_actions:
            logger.info(
                "Autonomous: skipping user-blocked action %s (%s)",
                rec.action_type, rec.id,
            )
            continue

        if rec.confidence_score < _settings.confidence_threshold:
            logger.debug(
                "Autonomous: confidence %.2f < threshold %.2f for %s",
                rec.confidence_score, _settings.confidence_threshold, rec.id,
            )
            continue

        if rec.expiry_sim_time < sim_time:
            continue

        # Auto-apply this recommendation
        rec.applied = True
        rec.applied_at = sim_time

        log_entry = {
            "id": f"auto-{uuid4().hex[:12]}",
            "recommendation_id": rec.id,
            "action_type": rec.action_type.value,
            "description": rec.description,
            "confidence_score": rec.confidence_score,
            "applied_at": sim_time.isoformat(),
            "expected_impact": rec.expected_impact,
            "actual_outcome": None,  # Filled in 30 min later
            "outcome_measured_at": None,
        }
        _action_log.append(log_entry)
        if len(_action_log) > MAX_ACTION_LOG:
            _action_log.pop(0)

        # Also log to the analysis log
        _log_entry(AnalysisLogEntry(
            id=log_entry["id"],
            timestamp=sim_time,
            entry_type="autonomous_action",
            action=None,
            projected_outcome=None,
            operator_applied=False,
        ))

        actions_taken.append(log_entry)
        logger.info(
            "Autonomous: applied %s (confidence=%.2f) — %s",
            rec.action_type, rec.confidence_score, rec.description,
        )

        # Only apply one action per evaluation cycle
        break

    return actions_taken


def record_outcome(
    action_id: str,
    actual_outcome: dict,
    sim_time: datetime,
) -> None:
    """P2-4-2: Record the actual outcome of an auto-applied action."""
    for entry in _action_log:
        if entry["id"] == action_id:
            entry["actual_outcome"] = actual_outcome
            entry["outcome_measured_at"] = sim_time.isoformat()
            break
