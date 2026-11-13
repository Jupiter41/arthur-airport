"""Prediction calibration from attributed, measured outcomes (roadmap G8, A58).

Inputs are durable ``ActionProposal`` documents: each executed proposal carries
its dispatch-time ``baseline`` (with the engine's ex-ante prediction) and an
``actual_outcome`` whose ``attribution`` compares the treated unit with untreated
comparable units over the same window. Only ``calibration_eligible``
attributions contribute; pre/post observations without a counterfactual never
move the calibration.

Per action type the module derives:

* ``impact_factor`` — realised effect / predicted effect. For security lanes
  this is attributed wait reduction / predicted wait reduction; for binary
  actions it is attributed lift over the untreated control rate / predicted
  success probability.
* ``confidence_factor`` — observed success rate / mean stated confidence.
* ``brier_score`` — mean squared error of the stated confidence.

Both factors are shrunk towards 1.0 with ``PRIOR_STRENGTH`` pseudo-observations
and clamped, so a handful of outcomes adjusts ranking gradually and an empty
history leaves the heuristic ranking unchanged. The snapshot is a pure function
of persisted proposals and is therefore rebuildable after any restart.
"""

from __future__ import annotations

from dataclasses import dataclass

CALIBRATION_VERSION = "calibration-v1"
PRIOR_STRENGTH = 5.0
FACTOR_MIN, FACTOR_MAX = 0.25, 2.0


@dataclass(frozen=True)
class Factors:
    impact: float = 1.0
    confidence: float = 1.0
    samples: int = 0


def _clamp(value: float) -> float:
    return max(FACTOR_MIN, min(FACTOR_MAX, value))


def shrink(ratio: float, samples: int, prior: float = PRIOR_STRENGTH) -> float:
    """Posterior-mean style shrinkage of a ratio towards the neutral 1.0."""
    if samples <= 0:
        return 1.0
    return _clamp((samples * ratio + prior) / (samples + prior))


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _sample(document: dict) -> dict | None:
    if document.get("status") != "executed":
        return None
    attribution = (document.get("actual_outcome") or {}).get("attribution") or {}
    if not attribution.get("calibration_eligible"):
        return None
    effect = _number(attribution.get("attributed_effect"))
    confidence = _number(document.get("confidence_score"))
    if effect is None or confidence is None:
        return None
    if attribution.get("metric") == "security_wait_minutes":
        predicted = _number(attribution.get("predicted_effect"))
        if predicted is None or predicted >= 0:
            return None
        # Negative deltas are improvements; compare reductions.
        return {"realised": -effect, "predicted": -predicted, "success": int(effect < 0),
                "confidence": confidence}
    predicted = _number(attribution.get("predicted_probability"))
    if predicted is None:
        return None
    return {"realised": effect, "predicted": predicted,
            "success": int(attribution.get("treated_after") == 1 and effect > 0),
            "confidence": confidence}


def build(documents: list[dict]) -> dict:
    """Compute the calibration snapshot from persisted proposal documents."""
    grouped: dict[str, list[dict]] = {}
    measured = 0
    for document in documents:
        if document.get("status") == "executed" and document.get("actual_outcome") is not None:
            measured += 1
        sample = _sample(document)
        if sample is not None:
            grouped.setdefault(document.get("action_type", ""), []).append(sample)
    by_type: dict[str, dict] = {}
    for action_type, samples in sorted(grouped.items()):
        n = len(samples)
        predicted = sum(s["predicted"] for s in samples)
        realised = sum(s["realised"] for s in samples)
        mean_confidence = sum(s["confidence"] for s in samples) / n
        success_rate = sum(s["success"] for s in samples) / n
        effect_ratio = realised / predicted if predicted > 0 else 1.0
        confidence_ratio = success_rate / mean_confidence if mean_confidence > 0 else 1.0
        by_type[action_type] = {
            "samples": n,
            "predicted_total": round(predicted, 4),
            "realised_total": round(realised, 4),
            "effect_ratio": round(effect_ratio, 4),
            "impact_factor": round(shrink(effect_ratio, n), 4),
            "mean_confidence": round(mean_confidence, 4),
            "success_rate": round(success_rate, 4),
            "confidence_factor": round(shrink(confidence_ratio, n), 4),
            "brier_score": round(sum((s["confidence"] - s["success"]) ** 2 for s in samples) / n, 4),
        }
    return {
        "version": CALIBRATION_VERSION,
        "prior_strength": PRIOR_STRENGTH,
        "factor_bounds": [FACTOR_MIN, FACTOR_MAX],
        "measured_outcomes": measured,
        "eligible_samples": sum(v["samples"] for v in by_type.values()),
        "by_action_type": by_type,
        "causal_claim": False,
        "note": ("Attributed against untreated comparable units in the same window; "
                 "not a randomised causal estimate."),
    }


_snapshot: dict = build([])


def refresh(documents: list[dict]) -> dict:
    global _snapshot
    _snapshot = build(documents)
    return _snapshot


def current() -> dict:
    return _snapshot


def factors(action_type: str, snapshot: dict | None = None) -> Factors:
    entry = ((snapshot or _snapshot).get("by_action_type") or {}).get(action_type)
    if not entry:
        return Factors()
    return Factors(impact=float(entry["impact_factor"]), confidence=float(entry["confidence_factor"]),
                   samples=int(entry["samples"]))
