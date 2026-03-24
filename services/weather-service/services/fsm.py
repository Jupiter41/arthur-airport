"""Weather FSM — 4-state finite state machine with transition constraints."""

import random

# States in order of increasing severity
SEVERITY = ["CAVOK", "VMC", "IMC", "LIFR"]

# Transition probabilities per simulated hour
TRANSITION_MATRIX = {
    "CAVOK": {"CAVOK": 0.85, "VMC": 0.13, "IMC": 0.02, "LIFR": 0.00},
    "VMC":   {"CAVOK": 0.20, "VMC": 0.65, "IMC": 0.14, "LIFR": 0.01},
    "IMC":   {"CAVOK": 0.05, "VMC": 0.30, "IMC": 0.55, "LIFR": 0.10},
    "LIFR":  {"CAVOK": 0.00, "VMC": 0.05, "IMC": 0.35, "LIFR": 0.60},
}


def evaluate_transition(current: str, rng: random.Random | None = None) -> str:
    """Evaluate a single FSM transition from the current state.

    Uses the transition matrix to probabilistically select the next state.
    Rejects transitions that skip more than 1 severity step (e.g. LIFR->CAVOK).
    If rejected, the FSM stays in the current state.

    Args:
        current: Current weather category (CAVOK, VMC, IMC, LIFR)
        rng: Optional seeded Random instance for determinism

    Returns:
        The next weather category
    """
    if current not in TRANSITION_MATRIX:
        raise ValueError(f"Invalid weather category: {current}")

    chooser = rng if rng else random
    row = TRANSITION_MATRIX[current]
    candidate = chooser.choices(
        list(row.keys()), weights=list(row.values())
    )[0]

    # Reject jumps of more than 1 severity step
    current_idx = SEVERITY.index(current)
    candidate_idx = SEVERITY.index(candidate)
    if abs(candidate_idx - current_idx) > 1:
        return current  # stay — re-evaluate next hour

    return candidate


def is_valid_transition(from_state: str, to_state: str) -> bool:
    """Check if a transition between two states is valid (<=1 step)."""
    from_idx = SEVERITY.index(from_state)
    to_idx = SEVERITY.index(to_state)
    return abs(to_idx - from_idx) <= 1
