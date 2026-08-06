"""Single source of truth for aircraft body-class classification.

Previously each service defined its own ``WIDE_BODY_TYPES`` set, and they had
**drifted**: cost-service listed ``A359`` but not ``B748``/``A380``; planning and
flight-service listed ``B748``/``A380`` but not ``A359``; carbon-tracking listed
the union. A ``B748`` was therefore wide-body for gate assignment but narrow-body
for ground-handling cost — an inconsistency across the twin.

The canonical lists live in ``aircraft_reference.json`` next to this module and
are loaded once here. Import ``WIDE_BODY_TYPES``, ``REGIONAL_TYPES`` and
``aircraft_family`` from ``_common.aircraft`` instead of redefining them.
"""

from __future__ import annotations

import json
from pathlib import Path

_REFERENCE_PATH = Path(__file__).with_name("aircraft_reference.json")

with _REFERENCE_PATH.open() as _f:
    _reference = json.load(_f)

# frozenset: shared, read-only — callers must not mutate the canonical set.
WIDE_BODY_TYPES: frozenset[str] = frozenset(_reference["wide_body_types"])
REGIONAL_TYPES: frozenset[str] = frozenset(_reference["regional_types"])


def aircraft_family(aircraft_type: str) -> str:
    """Classify an aircraft type as ``"wide"``, ``"regional"`` or ``"narrow"``.

    Unknown types default to ``"narrow"`` — the safe majority class.
    """
    if aircraft_type in WIDE_BODY_TYPES:
        return "wide"
    if aircraft_type in REGIONAL_TYPES:
        return "regional"
    return "narrow"
