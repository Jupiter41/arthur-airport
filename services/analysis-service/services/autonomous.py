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

from models.domain import (
    ActionType,
    AutonomousSettings,
    Recommendation,
)
from services import approval_queue

logger = logging.getLogger(__name__)

# ── Autonomous settings (mutable at runtime) ────────────────

_settings = AutonomousSettings()

# P2-4-4: Safety guards — these actions ALWAYS require human confirmation
SAFETY_GUARDED_ACTIONS: set[ActionType] = {
    ActionType.GROUND_DELAY_PROGRAM,
    ActionType.REBOOK_PASSENGERS,
    # Containing/resolving an incident is operationally significant — always
    # route through human approval rather than auto-execute.
    ActionType.CONTAIN_INCIDENT,
    ActionType.RESOLVE_INCIDENT,
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

        if rec.expiry_sim_time <= sim_time:
            continue
        if any(p.bottleneck_id == rec.bottleneck_id and p.action_type == rec.action_type.value
               and p.status in {approval_queue.PENDING, approval_queue.APPROVED, approval_queue.DISPATCHED}
               for p in approval_queue.list_all()):
            continue

        from _common.commands import action_command
        if (rec.action_type not in SAFETY_GUARDED_ACTIONS
                and action_command(rec.action_type.value, rec.parameters) is None):
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

        # Approved is an intent, not an executed action. The adapter dispatches
        # the proposal and only an owning service receipt records application.
        proposal = approval_queue.propose(
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
        _bottleneck_cooldowns[rec.bottleneck_id] = sim_time
        actions_taken.append(proposal.to_dict())

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
    """Create an executable proposal by id; execution waits for owner receipt.

    Returns None for an unknown/already submitted recommendation and raises
    ValueError for an expired or advisory action. The adapter persists and sends.
    """
    rec = next((r for r in recommendations if r.id == recommendation_id), None)
    if rec is None or rec.applied:
        return None

    if rec.expiry_sim_time <= sim_time:
        raise ValueError("Recommendation has expired")
    from _common.commands import action_command
    if action_command(rec.action_type.value, rec.parameters) is None:
        raise ValueError("Action is advisory: no executable command with these parameters")
    if any((p.recommendation_id == rec.id or (
        p.bottleneck_id == rec.bottleneck_id and p.action_type == rec.action_type.value
        and p.parameters == rec.parameters
    )) and p.status not in {
        approval_queue.FAILED, approval_queue.REJECTED,
    } for p in approval_queue.list_all()):
        return None
    proposal = approval_queue.propose(
        action_type=rec.action_type.value,
        description=rec.description,
        parameters=dict(rec.parameters),
        confidence_score=rec.confidence_score,
        proposed_by=initiated_by,
        proposed_at=sim_time,
        recommendation_id=rec.id,
        bottleneck_id=rec.bottleneck_id,
        requires_human=rec.action_type in SAFETY_GUARDED_ACTIONS,
    )
    _bottleneck_cooldowns[rec.bottleneck_id] = sim_time
    return proposal.to_dict()


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
    log_entry = execution_entry(proposal, sim_time, decided_by=decided_by)
    _action_log.append(log_entry)
    if len(_action_log) > MAX_ACTION_LOG:
        _action_log.pop(0)
    logger.info("Approved proposal %s executed", proposal["id"])
    return log_entry


def execution_entry(proposal: dict, sim_time: datetime, *, decided_by: str | None = None) -> dict:
    """Pure confirmed-log representation shared by persistence and API reads."""
    return {
        "id": f"action-{proposal['id']}",
        "recommendation_id": proposal.get("recommendation_id"),
        "proposal_id": proposal.get("id"),
        "status": "executed",
        "action_type": proposal.get("action_type"),
        "description": proposal.get("description"),
        "confidence_score": proposal.get("confidence_score"),
        "applied_at": sim_time.isoformat(),
        "initiated_by": proposal.get("proposed_by"),
        "approved_by": decided_by or proposal.get("decided_by") or proposal["proposed_by"],
        "parameters": dict(proposal.get("parameters") or {}),
        "actual_outcome": None,
        "outcome_measured_at": None,
    }


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
        from kafka.consumer import get_active_bottlenecks
        active = list(get_active_bottlenecks().values())
        state_dict = state_from_operational(state, active_bottleneck_count=len(active))
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

        # Policy selection is advisory until it identifies a concrete action.
        # Reuse the same guarded recommendation path as rule-based control.
        from services.recommender import generate_recommendations
        recommendations = generate_recommendations(
            state, active, max_total=100,
        )
        selected = [r for r in recommendations if r.action_type.value == action_name]
        return evaluate_and_apply(selected[:1], sim_time)

    except Exception:
        logger.exception("RL agent evaluation failed")
        return []
