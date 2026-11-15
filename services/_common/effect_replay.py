"""Replay durable ex-ante projections against G8 outcomes without fitting to them."""

from __future__ import annotations

import math
from statistics import median

from _common.airport_config import EffectParameters
from _common.effects import Action, EffectState, EFFECT_MODEL_VERSION, MODELLED_ACTIONS, apply


def validate_replay(documents: list[dict]) -> dict:
    groups: dict[str, list[float]] = {kind: [] for kind in sorted(MODELLED_ACTIONS)}
    excluded: dict[str, int] = {}
    seen: set[str] = set()
    for document in documents:
        identity = document.get("id")
        baseline = document.get("baseline") or {}
        attribution = (document.get("actual_outcome") or {}).get("attribution") or {}
        replay = baseline.get("effect_replay")
        reason = None
        if not identity or identity in seen:
            reason = "missing_or_duplicate_id"
        elif document.get("status") != "executed" or not attribution.get("calibration_eligible"):
            reason = "ineligible_outcome"
        elif baseline.get("effect_model_version") != EFFECT_MODEL_VERSION or not replay:
            reason = "legacy_or_missing_replay"
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        seen.add(identity)
        try:
            kind = document["action_type"]
            actions = [Action.model_validate(a) for a in replay["actions"]]
            if len(actions) != 1 or actions[0].action_type != kind or actions[0].parameters != document["parameters"]:
                raise ValueError("replay action does not match proposal")
            result = apply(actions, EffectState.model_validate(replay["state"]), replay["horizon"],
                           params=EffectParameters.model_validate(replay["params"]), factors=replay["factors"])
            prediction = result.predictions[kind]
            predicted = float(prediction.get("delta", prediction.get("probability")))
            observed = float(attribution["attributed_effect"])
            if not math.isfinite(predicted) or not math.isfinite(observed):
                raise ValueError("nonfinite effect")
            error = abs(predicted - observed) / abs(observed) if observed else abs(predicted)
            groups[kind].append(error)
        except (KeyError, TypeError, ValueError):
            excluded["invalid_replay"] = excluded.get("invalid_replay", 0) + 1
    by_type = {}
    for kind, errors in groups.items():
        value = median(errors) if errors else None
        by_type[kind] = {"samples": len(errors), "median_absolute_relative_error": value,
                         "status": "unvalidated" if len(errors) < 20 else "passed" if value <= 0.25 else "failed"}
    return {"effect_model_version": EFFECT_MODEL_VERSION, "minimum_samples": 20,
            "maximum_median_absolute_relative_error": 0.25, "by_action_type": by_type,
            "excluded": excluded, "causal_claim": False}
