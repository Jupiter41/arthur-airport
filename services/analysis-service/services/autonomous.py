"""Autonomous operations mode.

When enabled, automatically applies the top recommendation every N sim-minutes
if its confidence score exceeds the configured threshold.

Safety guards prevent autonomous application of destructive actions
(flight cancellation, runway closure, terminal evacuation).

Modes (P5-1-5):
  - off: No autonomous actions
  - rule_based: Apply all recommendations meeting threshold
  - threshold: Apply top recommendation only if confidence > threshold
  - rl_agent: Use trained PPO policy to select actions

P2-4-1 through P2-4-4, P5-1-5.
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
from services import approval_queue
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

# Cooldown tracking: bottleneck_id → sim_time when action was last applied
# Prevents the same recommendation from being re-applied every cycle
_bottleneck_cooldowns: dict[str, datetime] = {}
COOLDOWN_MINUTES = 30  # Don't re-apply for the same bottleneck within this window


def get_settings() -> AutonomousSettings:
    return _settings


def update_settings(new: AutonomousSettings) -> AutonomousSettings:
    global _settings
    # Derive 'enabled' from mode: any mode other than "off" means enabled
    from models.domain import AutonomousMode
    new.enabled = new.mode != AutonomousMode.OFF
    _settings = new
    logger.info(
        "Autonomous mode=%s enabled=%s (threshold=%.2f, interval=%d min)",
        _settings.mode.value,
        _settings.enabled,
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
    Includes cooldown logic to prevent the same bottleneck from being
    actioned repeatedly.
    """
    if not _settings.enabled:
        return []

    # Expire old cooldowns
    expired = [
        bid for bid, t in _bottleneck_cooldowns.items()
        if (sim_time - t).total_seconds() > COOLDOWN_MINUTES * 60
    ]
    for bid in expired:
        del _bottleneck_cooldowns[bid]

    actions_taken = []

    for rec in recommendations:
        if rec.applied:
            continue

        # Skip if this bottleneck is still in cooldown from a recent action
        if rec.bottleneck_id in _bottleneck_cooldowns:
            logger.debug(
                "Autonomous: skipping %s — bottleneck %s in cooldown",
                rec.action_type, rec.bottleneck_id,
            )
            continue

        if rec.expiry_sim_time < sim_time:
            continue

        # A9: route every candidate through the approval queue. The gating rule
        # decides auto-apply vs human-approval vs block/skip.
        verdict = approval_queue.classify(
            rec.action_type.value,
            rec.confidence_score,
            safety_guarded=rec.action_type in SAFETY_GUARDED_ACTIONS,
            blocked=rec.action_type in _settings.blocked_actions,
            threshold=_settings.confidence_threshold,
        )

        if verdict == approval_queue.BLOCK:
            logger.info(
                "Autonomous: skipping user-blocked action %s (%s)",
                rec.action_type, rec.id,
            )
            continue

        if verdict == approval_queue.SKIP:
            logger.debug(
                "Autonomous: confidence %.2f < threshold %.2f for %s",
                rec.confidence_score, _settings.confidence_threshold, rec.id,
            )
            continue

        if verdict == approval_queue.HUMAN:
            # Safety-guarded: surface for human Approve/Reject instead of
            # silently dropping. The recommendation is NOT applied yet; the
            # cooldown is registered so we don't re-propose the same bottleneck
            # every cycle while it awaits a decision.
            approval_queue.propose(
                action_type=rec.action_type.value,
                description=rec.description,
                parameters=dict(rec.parameters),
                confidence_score=rec.confidence_score,
                proposed_by="autonomous",
                proposed_at=sim_time,
                recommendation_id=rec.id,
                bottleneck_id=rec.bottleneck_id,
                requires_human=True,
            )
            _bottleneck_cooldowns[rec.bottleneck_id] = sim_time
            logger.info(
                "Autonomous: proposed safety-guarded action %s (%s) for approval",
                rec.action_type, rec.id,
            )
            continue

        # verdict == AUTO — auto-apply this recommendation
        rec.applied = True
        rec.applied_at = sim_time

        # Record an auto-approved+executed proposal for a unified, auditable trail.
        _proposal = approval_queue.propose(
            action_type=rec.action_type.value,
            description=rec.description,
            parameters=dict(rec.parameters),
            confidence_score=rec.confidence_score,
            proposed_by="autonomous",
            proposed_at=sim_time,
            recommendation_id=rec.id,
            bottleneck_id=rec.bottleneck_id,
            requires_human=False,
        )
        approval_queue.mark_executed(_proposal.id, sim_time)

        # Record cooldown so we don't re-apply for this bottleneck
        _bottleneck_cooldowns[rec.bottleneck_id] = sim_time

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

        # In rule_based mode, apply all qualifying actions;
        # in threshold mode, apply only the top one per cycle
        from models.domain import AutonomousMode
        if _settings.mode != AutonomousMode.RULE_BASED:
            break

    return actions_taken


def apply_recommendation(
    recommendations: list[Recommendation],
    recommendation_id: str,
    sim_time: datetime,
    *,
    initiated_by: str = "operator",
) -> dict | None:
    """Apply a single recommendation by id (manual operator "Apply").

    This is the real, non-theatrical replacement for the old client-side
    what-if projection: it marks the recommendation applied, records it in the
    action log (tagged with who initiated it), registers the bottleneck
    cooldown so the autonomous engine won't immediately re-action it, and
    returns the log entry so the caller can emit the corresponding event.

    Returns the log entry on success, or ``None`` if the recommendation id is
    unknown or already applied. Pure w.r.t. I/O — no Kafka/Neo4j here; the
    caller emits the event.
    """
    rec = next((r for r in recommendations if r.id == recommendation_id), None)
    if rec is None or rec.applied:
        return None

    rec.applied = True
    rec.applied_at = sim_time
    _bottleneck_cooldowns[rec.bottleneck_id] = sim_time

    log_entry = {
        "id": f"op-{uuid4().hex[:12]}",
        "recommendation_id": rec.id,
        "action_type": rec.action_type.value,
        "description": rec.description,
        "confidence_score": rec.confidence_score,
        "applied_at": sim_time.isoformat(),
        "expected_impact": rec.expected_impact,
        "initiated_by": initiated_by,
        "parameters": dict(rec.parameters),
        "actual_outcome": None,
        "outcome_measured_at": None,
    }
    _action_log.append(log_entry)
    if len(_action_log) > MAX_ACTION_LOG:
        _action_log.pop(0)

    logger.info(
        "Recommendation %s applied by %s — %s",
        rec.id, initiated_by, rec.description,
    )
    return log_entry


def record_proposal_execution(
    proposal: dict,
    sim_time: datetime,
    *,
    decided_by: str,
) -> dict:
    """Record an action-log entry for an approved+executed proposal.

    Produces the same log shape as an autonomous/operator apply so the existing
    ``record_outcome`` can later fill in the measured outcome (30 min later).
    Returns the log entry for the caller to emit as an event.
    """
    log_entry = {
        "id": f"appr-{uuid4().hex[:12]}",
        "recommendation_id": proposal.get("recommendation_id"),
        "proposal_id": proposal.get("id"),
        "action_type": proposal.get("action_type"),
        "description": proposal.get("description"),
        "confidence_score": proposal.get("confidence_score"),
        "applied_at": sim_time.isoformat(),
        "initiated_by": proposal.get("proposed_by"),
        "approved_by": decided_by,
        "parameters": dict(proposal.get("parameters") or {}),
        "actual_outcome": None,
        "outcome_measured_at": None,
    }
    _action_log.append(log_entry)
    if len(_action_log) > MAX_ACTION_LOG:
        _action_log.pop(0)
    logger.info(
        "Approved proposal %s executed (approved_by=%s) — %s",
        proposal.get("id"), decided_by, proposal.get("description"),
    )
    return log_entry


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


def evaluate_rl_agent(
    state,
    sim_time: datetime,
) -> list[dict]:
    """P5-1-5: Use trained RL agent to select and apply an action.

    Called when autonomous mode is 'rl_agent'. Uses the PPO policy
    to predict an action from the current observation, then logs it.
    """
    from services.rl.agent import is_loaded, predict_action, get_action_name, load_policy
    from services.rl.env import AirportOpsEnv, state_from_operational

    # Lazy-load RL policy
    if not is_loaded():
        if not load_policy():
            logger.warning("RL agent requested but no model available")
            return []

    # Convert operational state to RL observation
    try:
        state_dict = state_from_operational(state)
        env = AirportOpsEnv(initial_state=state_dict)
        obs, _ = env.reset(options={"state": state_dict})

        action_idx, confidence = predict_action(obs)
        action_name = get_action_name(action_idx)

        if action_idx == 0:  # no_action
            return []

        if confidence < _settings.confidence_threshold:
            logger.debug(
                "RL agent: confidence %.2f < threshold %.2f for %s",
                confidence, _settings.confidence_threshold, action_name,
            )
            return []

        log_entry = {
            "id": f"rl-{uuid4().hex[:12]}",
            "action_type": action_name,
            "action_index": action_idx,
            "description": f"RL agent selected: {action_name}",
            "confidence_score": confidence,
            "applied_at": sim_time.isoformat(),
            "mode": "rl_agent",
            "actual_outcome": None,
            "outcome_measured_at": None,
        }
        _action_log.append(log_entry)
        if len(_action_log) > MAX_ACTION_LOG:
            _action_log.pop(0)

        logger.info(
            "RL agent: applied %s (confidence=%.2f)",
            action_name, confidence,
        )
        return [log_entry]

    except Exception:
        logger.exception("RL agent evaluation failed")
        return []
