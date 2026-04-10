"""RL agent loading and inference for autonomous mode (P5-1-5).

Provides a PPO-based policy that can be used as an alternative to
the rule-based recommendation engine in autonomous mode.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default model path
MODEL_PATH = os.getenv(
    "RL_MODEL_PATH",
    str(Path(__file__).parent.parent.parent / "models" / "rl_policy.zip"),
)

_policy = None
_loaded = False


def load_policy(path: str | None = None) -> bool:
    """Load a trained PPO policy from disk.

    Returns True if loaded successfully, False otherwise.
    """
    global _policy, _loaded

    model_path = path or MODEL_PATH
    if not Path(model_path).exists():
        logger.info("No RL model found at %s — RL agent unavailable", model_path)
        _loaded = False
        return False

    try:
        from stable_baselines3 import PPO
        _policy = PPO.load(model_path)
        _loaded = True
        logger.info("RL policy loaded from %s", model_path)
        return True
    except Exception:
        logger.exception("Failed to load RL policy from %s", model_path)
        _loaded = False
        return False


def is_loaded() -> bool:
    """Check if an RL policy is currently loaded."""
    return _loaded


def predict_action(observation: np.ndarray) -> tuple[int, float]:
    """Predict the best action given the current observation.

    Returns (action_index, confidence) where confidence is the
    probability of the chosen action.
    """
    if not _loaded or _policy is None:
        return 0, 0.0  # no_action fallback

    try:
        action, _states = _policy.predict(observation, deterministic=True)
        # Get action probabilities for confidence estimation
        obs_tensor = _policy.policy.obs_to_tensor(observation.reshape(1, -1))[0]
        distribution = _policy.policy.get_distribution(obs_tensor)
        probs = distribution.distribution.probs.detach().cpu().numpy()[0]
        confidence = float(probs[int(action)])
        return int(action), confidence
    except Exception:
        logger.exception("RL prediction failed")
        return 0, 0.0


def get_action_name(action_idx: int) -> str:
    """Map action index to human-readable name."""
    from services.rl.env import ACTION_NAMES
    if 0 <= action_idx < len(ACTION_NAMES):
        return ACTION_NAMES[action_idx]
    return "unknown"
