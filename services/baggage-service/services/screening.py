"""DG (Dangerous Goods) screening — probabilistic detection + false positives.

Each baggage item passing through a screening zone is evaluated once.
Detection rates depend on DG class; clean items have a false positive rate.
"""

import logging
import os
import random

logger = logging.getLogger(__name__)

# Base detection rates per IATA DG class (from SPEC.md §4)
DETECTION_RATES: dict[str, float] = {
    "2": 0.88,  # gases
    "3": 0.91,  # flammable liquids
    "8": 0.95,  # corrosives
    "9": 0.72,  # miscellaneous
}

FALSE_POSITIVE_RATE: float = float(os.getenv("DG_FALSE_POSITIVE_RATE", "0.003"))


def screen_item(
    baggage_id: str,
    is_dg: bool,
    dg_class: str | None,
) -> str:
    """Screen a baggage item and return result.

    Returns:
        'clear' — item passes screening
        'flagged' — actual DG detected
        'false_positive' — clean item incorrectly flagged
    """
    if is_dg and dg_class:
        rate = DETECTION_RATES.get(dg_class, 0.80)
        if random.random() < rate:
            logger.info(
                "DG detected: baggage %s, class %s (rate %.0f%%)",
                baggage_id, dg_class, rate * 100,
            )
            return "flagged"

    # False positive on clean items
    if random.random() < FALSE_POSITIVE_RATE:
        logger.info("False positive: baggage %s", baggage_id)
        return "false_positive"

    return "clear"
